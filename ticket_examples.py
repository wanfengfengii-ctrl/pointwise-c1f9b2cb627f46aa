import argparse
import json
import re
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from correction.dictionary import PageCapacityError
from correction.request import correct_labels
from correction.targets import LabelEdit
from intake.package import accept_package
from publication.catalog import ReleaseNotFound, list_pages, load_page
from publication.page_format import decode_fixed_page_fields
from publication.receipts import Receipt, read_receipt
from publication.store import initialize_store, open_store
from reconciliation.statement import reconcile_release
from reconciliation.totals import LabelTotal
from review.open_artifact import read_page
from tests.fixtures import full_package

_CHECK = TestCase()
_BATCH = "ticket-example"
_EDITS = tuple(LabelEdit(10, row, "N") for row in range(3))


def _counts(connection):
    return tuple(
        connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("releases", "page_directory", "fixed_pages", "receipts")
    )


def _pages(database, release):
    with open_store(database) as connection:
        return tuple(load_page(connection, release, number) for number in list_pages(connection, release))


def _digests(pages):
    return tuple((page.page_number, sha256(page.content).hexdigest()) for page in pages)


def _check_child(database, parent, child, slots, n):
    original, unchanged = _pages(database, parent)
    revised, second = _pages(database, child)
    _CHECK.assertEqual((revised.page_number, second.page_number), (10, 4))
    _CHECK.assertEqual(second, unchanged)
    _CHECK.assertEqual(len(decode_fixed_page_fields(revised.content).dictionary), slots)
    parent_page = read_page(database, parent, original.page_number)
    child_page = read_page(database, child, revised.page_number)
    _CHECK.assertEqual(parent_page.observations[0].label, "A")
    _CHECK.assertEqual(child_page.extensions, parent_page.extensions)
    extension, = child_page.extensions
    _CHECK.assertEqual((extension.row_index, extension.raw, extension.references), (256, b"\x00\xff", ((0, "A"),)))
    _CHECK.assertEqual(
        [(row.row_index, row.label, row.reading) for row in child_page.observations[:n]],
        [(row, "N", row) for row in range(n)],
    )
    _CHECK.assertEqual(child_page.observations[n:], parent_page.observations[n:])
    _CHECK.assertIn(LabelTotal("N", n, n, sum(range(n))), reconcile_release(database, child))
    _CHECK.assertEqual(read_receipt(database, child), Receipt(child, _BATCH, parent))
    return _digests((revised, second))


def _reference(database, parent):
    with _CHECK.assertRaises(PageCapacityError) as failure:
        correct_labels(database, parent, _EDITS[:1])
    error = failure.exception
    _CHECK.assertEqual((error.page_number, error.required_slots), (10, 257))
    with open_store(database) as observer:
        _CHECK.assertEqual(_counts(observer), (1, 2, 2, 1))
    evidence = []
    for n, slots in ((2, 256), (3, 255)):
        child = correct_labels(database, parent, _EDITS[:n])
        evidence.append({"slots": slots, "pages": _check_child(database, parent, child, slots, n)})
    return {"v1_rejected_slots": error.required_slots, "v1_successful_batches": evidence}


def _preview_pages(preview, version, unchanged):
    found, pages = preview
    _CHECK.assertEqual(found, version)
    _CHECK.assertIsInstance(pages, tuple)
    _CHECK.assertEqual(tuple(number for number, _ in pages), (10, 4))
    _CHECK.assertTrue(all(re.fullmatch(r"[0-9a-f]{64}", digest) for _, digest in pages))
    _CHECK.assertEqual(pages[1], unchanged)
    return pages


def _workflow(database, parent):
    from correction.request import preview_correction, record_edits
    from publication.commit import sign_correction

    class Interrupted(RuntimeError):
        pass

    ticket = "night-shift"
    unchanged = _digests(_pages(database, parent))[1]
    attempted = []
    with open_store(database) as observer:
        prior = _counts(observer)
        _CHECK.assertEqual(prior, (1, 2, 2, 1))

        def interrupt(release):
            attempted.append(release)
            _CHECK.assertEqual(_counts(observer), prior)
            with _CHECK.assertRaises(ReleaseNotFound):
                read_receipt(database, release)
            raise Interrupted("stopped before signature commit")

        first = record_edits(database, ticket, parent, _EDITS[:1])
        _CHECK.assertEqual(first, 1)
        with _CHECK.assertRaises(PageCapacityError) as failure:
            preview_correction(database, ticket, first)
        _CHECK.assertEqual((failure.exception.page_number, failure.exception.required_slots), (10, 257))
        with _CHECK.assertRaises(ValueError):
            sign_correction(database, ticket, first)

        second = record_edits(database, ticket, parent, _EDITS[1:2])
        _CHECK.assertEqual(second, 2)
        second_pages = _preview_pages(preview_correction(database, ticket, second), second, unchanged)
        third = record_edits(database, ticket, parent, _EDITS[2:])
        _CHECK.assertEqual(third, 3)
        for ineligible in (second, third):
            with _CHECK.assertRaises(ValueError):
                sign_correction(database, ticket, ineligible)
        third_pages = _preview_pages(preview_correction(database, ticket, third), third, unchanged)
        _CHECK.assertNotEqual(second_pages[0], third_pages[0])
        _CHECK.assertEqual(_counts(observer), prior)
        with _CHECK.assertRaises(Interrupted):
            sign_correction(database, ticket, third, before_commit=interrupt)
        _CHECK.assertEqual(len(attempted), 1)
        _CHECK.assertEqual(_counts(observer), prior)
        with _CHECK.assertRaises(ReleaseNotFound):
            read_receipt(database, attempted[0])

    initialize_store(database)
    signed = sign_correction(database, ticket, third)
    replay = sign_correction(database, ticket, third, before_commit=interrupt)
    _CHECK.assertEqual(replay, signed)
    _CHECK.assertEqual(len(attempted), 1)
    with _CHECK.assertRaises(ValueError):
        sign_correction(database, ticket, second)
    with _CHECK.assertRaises(ValueError):
        record_edits(database, ticket, parent, _EDITS[:1])
    with open_store(database) as observer:
        _CHECK.assertEqual(_counts(observer), (2, 4, 4, 2))
    _CHECK.assertEqual(_check_child(database, parent, signed, 255, 3), third_pages)
    return {
        "draft_required_slots": failure.exception.required_slots,
        "previous_preview": {"version": second, "pages": second_pages},
        "signed_preview": {"version": third, "pages": third_pages},
        "rolled_back_attempt": attempted[0],
        "parent": parent,
        "signed_release": signed,
        "replayed_release": replay,
        "N_net": 3,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="仪器更正单样例核账")
    parser.add_argument("mode", choices=("v1", "workflow"))
    mode = parser.parse_args(argv).mode
    with TemporaryDirectory(prefix="instrument-ticket-example-") as directory:
        database = Path(directory) / "example.sqlite"
        initialize_store(database)
        parent = accept_package(database, _BATCH, full_package(pinned=True))
        evidence = _reference(database, parent) if mode == "v1" else _workflow(database, parent)
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
