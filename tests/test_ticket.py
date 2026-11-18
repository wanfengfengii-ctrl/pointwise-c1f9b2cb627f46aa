from hashlib import sha256

from correction.dictionary import PageCapacityError
from correction.request import preview_correction, record_edits
from correction.targets import CorrectionTargetError, LabelEdit
from intake.package import accept_package
from publication.catalog import ReleaseNotFound, list_pages, load_page
from publication.commit import sign_correction
from publication.receipts import Receipt, read_receipt
from publication.store import initialize_store, open_store
from reconciliation.statement import compare_releases, reconcile_release
from reconciliation.totals import LabelTotal
from review.observations import ObservationEvidence
from review.open_artifact import read_page
from tests.fixtures import DatabaseCase, full_package, sample_bytes

_EDITS = tuple(LabelEdit(10, row, 'N') for row in range(3))


class Interrupted(RuntimeError):
    pass


def _digests(database, release):
    with open_store(database) as connection:
        return tuple(
            (number, sha256(load_page(connection, release, number).content).hexdigest())
            for number in list_pages(connection, release)
        )


def _draft_counts(database):
    with open_store(database) as connection:
        return tuple(
            connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
            for table in ('correction_tickets', 'correction_edits', 'correction_previews', 'correction_signatures')
        )


class TicketRecording(DatabaseCase):
    def test_first_batch_fixes_parent_and_versions(self):
        parent = accept_package(self.database, 'ticket', full_package(pinned=True))
        self.assertEqual(record_edits(self.database, 'day-shift', parent, _EDITS[:1]), 1)
        self.assertEqual(record_edits(self.database, 'day-shift', parent, _EDITS[1:2]), 2)
        self.assertEqual(_draft_counts(self.database), (1, 2, 0, 0))
        with open_store(self.database) as connection:
            rows = connection.execute(
                'SELECT page_no, row_index, label FROM correction_edits ORDER BY row_index'
            ).fetchall()
        self.assertEqual(rows, [(10, 0, 'N'), (10, 1, 'N')])

    def test_overwrite_keeps_other_coordinates(self):
        parent = accept_package(self.database, 'overwrite', full_package(pinned=True))
        record_edits(self.database, 'ticket', parent, _EDITS[:2])
        self.assertEqual(record_edits(self.database, 'ticket', parent, [LabelEdit(10, 1, 'Q')]), 2)
        with open_store(self.database) as connection:
            rows = connection.execute(
                'SELECT page_no, row_index, label FROM correction_edits ORDER BY row_index'
            ).fetchall()
        self.assertEqual(rows, [(10, 0, 'N'), (10, 1, 'Q')])

    def test_invalid_batch_keeps_state(self):
        parent = accept_package(self.database, 'invalid', full_package(pinned=True))
        record_edits(self.database, 'ticket', parent, _EDITS[:1])
        with self.assertRaises(CorrectionTargetError):
            record_edits(self.database, 'ticket', parent, [LabelEdit(10, 0, 'N'), LabelEdit(10, 0, 'Q')])
        with self.assertRaises(CorrectionTargetError):
            record_edits(self.database, 'ticket', parent, [LabelEdit(10, 256, 'Q')])
        with self.assertRaises(CorrectionTargetError):
            record_edits(self.database, 'ticket', parent, [])
        with open_store(self.database) as connection:
            version = connection.execute("SELECT version FROM correction_tickets WHERE ticket = 'ticket'").fetchone()
        self.assertEqual(version, (1,))
        self.assertEqual(_draft_counts(self.database), (1, 1, 0, 0))

    def test_invalid_batch_creates_no_ticket(self):
        parent = accept_package(self.database, 'fresh', full_package(pinned=True))
        with self.assertRaises(CorrectionTargetError):
            record_edits(self.database, 'new-ticket', parent, [LabelEdit(4, 1, 'Q')])
        self.assertEqual(_draft_counts(self.database), (0, 0, 0, 0))

    def test_parent_change_rejected(self):
        first = accept_package(self.database, 'first', full_package(pinned=True))
        second = accept_package(self.database, 'second', sample_bytes())
        record_edits(self.database, 'ticket', first, [LabelEdit(10, 0, 'N')])
        with self.assertRaises(ValueError):
            record_edits(self.database, 'ticket', second, [LabelEdit(10, 0, 'N')])
        with self.assertRaises(ReleaseNotFound):
            record_edits(self.database, 'ticket', 999, [LabelEdit(10, 0, 'N')])
        with self.assertRaises(ValueError):
            record_edits(self.database, '', first, [LabelEdit(10, 0, 'N')])
        with open_store(self.database) as connection:
            state = connection.execute("SELECT parent_id, version FROM correction_tickets").fetchall()
        self.assertEqual(state, [(first, 1)])

    def test_overflowing_batch_is_persisted(self):
        parent = accept_package(self.database, 'overflow', full_package(pinned=True))
        self.assertEqual(record_edits(self.database, 'ticket', parent, _EDITS[:1]), 1)
        with self.assertRaises(PageCapacityError) as failure:
            preview_correction(self.database, 'ticket', 1)
        self.assertEqual(failure.exception.required_slots, 257)
        with open_store(self.database) as connection:
            version = connection.execute("SELECT version FROM correction_tickets").fetchone()
            previews = connection.execute('SELECT count(*) FROM correction_previews').fetchone()
        self.assertEqual((version, previews), ((1,), (0,)))


class TicketPreview(DatabaseCase):
    def test_preview_order_unchanged_page_and_digests(self):
        parent = accept_package(self.database, 'preview', full_package(pinned=True))
        record_edits(self.database, 'ticket', parent, _EDITS[:1])
        self.assertEqual(record_edits(self.database, 'ticket', parent, _EDITS[1:2]), 2)
        version, pages = preview_correction(self.database, 'ticket', 2)
        self.assertEqual(version, 2)
        self.assertIsInstance(pages, tuple)
        self.assertEqual(tuple(number for number, _ in pages), (10, 4))
        parent_pages = _digests(self.database, parent)
        self.assertEqual(pages[1], parent_pages[1])
        self.assertNotEqual(pages[0], parent_pages[0])
        self.assertEqual(preview_correction(self.database, 'ticket', 2), (2, pages))
        with open_store(self.database) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM releases').fetchone(), (1,))
        self.assertEqual(len(reconcile_release(self.database, parent)), 257)

    def test_preview_errors(self):
        parent = accept_package(self.database, 'errors', full_package(pinned=True))
        record_edits(self.database, 'ticket', parent, _EDITS[:1])
        for version in (0, -1, True, '1', 1.0):
            with self.subTest(version=version):
                with self.assertRaises(ValueError):
                    preview_correction(self.database, 'ticket', version)
        with self.assertRaises(KeyError):
            preview_correction(self.database, 'missing', 1)
        with self.assertRaises(ValueError):
            preview_correction(self.database, '', 1)
        record_edits(self.database, 'ticket', parent, _EDITS[1:2])
        with self.assertRaises(ValueError):
            preview_correction(self.database, 'ticket', 1)
        self.assertEqual(preview_correction(self.database, 'ticket', 2)[0], 2)

    def test_new_intake_discards_previous_preview(self):
        parent = accept_package(self.database, 'stale', full_package(pinned=True))
        record_edits(self.database, 'ticket', parent, _EDITS[:1])
        with self.assertRaises(PageCapacityError):
            preview_correction(self.database, 'ticket', 1)
        record_edits(self.database, 'ticket', parent, _EDITS[1:2])
        self.assertEqual(preview_correction(self.database, 'ticket', 2)[0], 2)
        record_edits(self.database, 'ticket', parent, _EDITS[2:3])
        with open_store(self.database) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM correction_previews').fetchone(), (0,))
        with self.assertRaises(ValueError):
            sign_correction(self.database, 'ticket', 3)


class TicketSignature(DatabaseCase):
    def test_sign_requires_preview(self):
        parent = accept_package(self.database, 'unsigned', full_package(pinned=True))
        record_edits(self.database, 'ticket', parent, _EDITS[:2])
        with self.assertRaises(ValueError):
            sign_correction(self.database, 'ticket', 1)
        with self.assertRaises(KeyError):
            sign_correction(self.database, 'missing', 1)
        with self.assertRaises(ValueError):
            sign_correction(self.database, '', 1)
        with self.assertRaises(ValueError):
            sign_correction(self.database, 'ticket', True)

    def test_sign_matches_preview_digests(self):
        parent = accept_package(self.database, 'signed', full_package(pinned=True))
        self.assertEqual(record_edits(self.database, 'ticket', parent, _EDITS), 1)
        version, preview = preview_correction(self.database, 'ticket', 1)
        signed = sign_correction(self.database, 'ticket', version)
        self.assertEqual(_digests(self.database, signed), preview)
        self.assertEqual(read_receipt(self.database, signed), Receipt(signed, 'signed', parent))
        self.assertEqual(read_page(self.database, signed, 10).observations[0], ObservationEvidence(10, 0, 'N', 0))
        self.assertIn(LabelTotal('N', 3, 3, 3), reconcile_release(self.database, signed))
        changes = {row.label: row for row in compare_releases(self.database, parent, signed)}
        self.assertEqual((changes['A'].records_delta, changes['N'].records_delta), (-1, 3))

    def test_preview_tampering_rejected(self):
        parent = accept_package(self.database, 'tampered', full_package(pinned=True))
        self.assertEqual(record_edits(self.database, 'ticket', parent, _EDITS[:2]), 1)
        version, _ = preview_correction(self.database, 'ticket', 1)
        with open_store(self.database) as connection:
            connection.execute(
                "UPDATE correction_previews SET digest = ? WHERE page_no = 10", ('0' * 64,)
            )
        with self.assertRaises(ValueError):
            sign_correction(self.database, 'ticket', version)
        self.assertEqual(_draft_counts(self.database)[3], 0)

    def test_rollback_then_retry_and_replay(self):
        parent = accept_package(self.database, 'retry', full_package(pinned=True))
        record_edits(self.database, 'ticket', parent, _EDITS[:2])
        self.assertEqual(record_edits(self.database, 'ticket', parent, _EDITS[2:3]), 2)
        version, preview = preview_correction(self.database, 'ticket', 2)
        attempted = []
        with open_store(self.database) as observer:
            prior = (1, 2, 2, 1)
            self.assertEqual(tuple(observer.execute(f'SELECT count(*) FROM {t}').fetchone()[0]
                                   for t in ('releases', 'page_directory', 'fixed_pages', 'receipts')), prior)

            def interrupt(release_id):
                attempted.append(release_id)
                self.assertEqual(tuple(observer.execute(f'SELECT count(*) FROM {t}').fetchone()[0]
                                       for t in ('releases', 'page_directory', 'fixed_pages', 'receipts')), prior)
                self.assertEqual(observer.execute('SELECT count(*) FROM correction_signatures').fetchone(), (0,))
                raise Interrupted('stopped before commit')

            with self.assertRaises(Interrupted):
                sign_correction(self.database, 'ticket', version, before_commit=interrupt)
        self.assertEqual(len(attempted), 1)
        with self.assertRaises(ReleaseNotFound):
            read_receipt(self.database, attempted[0])
        self.assertEqual(record_edits(self.database, 'ticket', parent, [LabelEdit(10, 0, 'N')]), 3)
        self.assertEqual(preview_correction(self.database, 'ticket', 3)[0], 3)
        initialize_store(self.database)
        signed = sign_correction(self.database, 'ticket', 3)
        replay = sign_correction(self.database, 'ticket', 3, before_commit=lambda release: (_ for _ in ()).throw(Interrupted()))
        self.assertEqual((signed, replay, len(attempted)), (signed, signed, 1))
        self.assertEqual(_digests(self.database, signed)[1], preview[1])
        with self.assertRaises(ValueError):
            sign_correction(self.database, 'ticket', 2)
        with self.assertRaises(ValueError):
            record_edits(self.database, 'ticket', parent, _EDITS[:1])
        with self.assertRaises(ValueError):
            preview_correction(self.database, 'ticket', 3)
        self.assertEqual(read_receipt(self.database, signed).parent_id, parent)
        self.assertEqual(reconcile_release(self.database, signed), reconcile_release(self.database, signed))

    def test_retry_same_version_after_rollback(self):
        parent = accept_package(self.database, 'same-version', full_package(pinned=True))
        record_edits(self.database, 'ticket', parent, _EDITS[:2])
        version, preview = preview_correction(self.database, 'ticket', 1)
        with self.assertRaises(Interrupted):
            sign_correction(
                self.database, 'ticket', version,
                before_commit=lambda release: (_ for _ in ()).throw(Interrupted('halt')),
            )
        initialize_store(self.database)
        self.assertEqual(preview_correction(self.database, 'ticket', version), (version, preview))
        signed = sign_correction(self.database, 'ticket', version)
        self.assertEqual(_digests(self.database, signed), preview)
        self.assertEqual(sign_correction(self.database, 'ticket', version), signed)

    def test_tickets_keep_separate_signatures(self):
        parent = accept_package(self.database, 'twin', full_package(pinned=True))
        record_edits(self.database, 'day', parent, _EDITS[:2])
        record_edits(self.database, 'night', parent, [LabelEdit(10, 0, 'Q'), LabelEdit(10, 1, 'Q')])
        day_version, day_preview = preview_correction(self.database, 'day', 1)
        night_version, night_preview = preview_correction(self.database, 'night', 1)
        self.assertNotEqual(day_preview[0], night_preview[0])
        day = sign_correction(self.database, 'day', day_version)
        night = sign_correction(self.database, 'night', night_version)
        self.assertNotEqual(day, night)
        self.assertEqual(read_page(self.database, day, 10).observations[0].label, 'N')
        self.assertEqual(read_page(self.database, night, 10).observations[0].label, 'Q')
        with self.assertRaises(KeyError):
            sign_correction(self.database, 'absent', 1)
        with self.assertRaises(KeyError):
            preview_correction(self.database, 'absent', 1)
