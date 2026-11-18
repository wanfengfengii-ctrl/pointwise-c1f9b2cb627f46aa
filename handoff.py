import argparse
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import ticket_examples
from correction.request import correct_labels, preview_correction, record_edits
from correction.targets import LabelEdit
from intake.package import accept_package
from publication.commit import sign_correction
from publication.receipts import read_receipt
from publication.store import initialize_store
from reconciliation.statement import compare_releases, reconcile_release
from review.open_artifact import read_page
from tests.fixtures import full_package

_ROOT = Path(__file__).resolve().parent


def _ordinary_rows(page):
    return [[row.row_index, row.label, row.reading] for row in page.observations]


def _totals(database, release):
    return [[row.label, row.records, row.non_null, row.net] for row in reconcile_release(database, release)]


def _shift_demo(database) -> bool:
    raw = (_ROOT / 'samples' / 'shift.json').read_bytes()
    original = accept_package(database, 'shift-demo', raw)
    replay = accept_package(database, 'shift-demo', raw)
    revised = correct_labels(database, original, [LabelEdit(10, 0, 'N')])
    del raw

    old_page = read_page(database, original, 10)
    page = read_page(database, revised, 10)
    second = read_page(database, revised, 4)
    extension = page.extensions[0]
    receipt = read_receipt(database, revised)
    actual = {
        'pages': [page.page_number, second.page_number],
        'old_first': _ordinary_rows(old_page),
        'new_first': _ordinary_rows(page),
        'new_second': _ordinary_rows(second),
        'extension': [extension.row_index, extension.raw.hex(), [list(ref) for ref in extension.references]],
        'replay_matches': replay == original,
        'receipt_matches': (receipt.release_id, receipt.batch_no, receipt.parent_id) == (revised, 'shift-demo', original),
    }
    expected = {
        'pages': [10, 4],
        'old_first': [[0, 'A', 6], [2, 'A', -6], [3, 'M', None]],
        'new_first': [[0, 'N', 6], [2, 'A', -6], [3, 'M', None]],
        'new_second': [[0, 'W', 5]],
        'extension': [1, '00ff', [[0, 'A']]],
        'replay_matches': True,
        'receipt_matches': True,
    }
    downstream_actual = {
        'old_totals': _totals(database, original),
        'new_totals': _totals(database, revised),
        'changes': [
            [row.label, row.records_delta, row.non_null_delta, row.net_delta]
            for row in compare_releases(database, original, revised)
        ],
    }
    downstream_expected = {
        'old_totals': [['A', 2, 2, 0], ['M', 1, 0, None], ['W', 1, 1, 5]],
        'new_totals': [['A', 1, 1, -6], ['M', 1, 0, None], ['N', 1, 1, 6], ['W', 1, 1, 5]],
        'changes': [['A', -1, -1, -6], ['M', 0, 0, None], ['N', 1, 1, 6], ['W', 0, 0, 0]],
    }
    if actual != expected or downstream_actual != downstream_expected:
        raise RuntimeError('shift sample differs from the hand-calculated handoff')
    print(f'原件 {original}，更正成果 {revised}，源批号 {receipt.batch_no}')
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': 'review_totals',
        'input': {'source': 'samples/shift.json', 'batch': 'shift-demo', 'edit': [10, 0, 'N']},
        'expected': expected,
        'actual': actual,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream_actual,
        'code_paths': ['intake/package.py', 'correction/request.py', 'publication/commit.py', 'review/open_artifact.py', 'reconciliation/statement.py'],
        'oracle': 'A starts with +6 and -6. The edit moves only +6 to N. M has one missing reading. W has one reading of 5.',
    }, ensure_ascii=False, sort_keys=True))
    return True


class _Interrupted(RuntimeError):
    pass


def _ticket_demo(database) -> bool:
    """Late intake, sign rollback/retry, reopen and review of one signed ticket."""
    parent = accept_package(database, 'ticket-demo', full_package(pinned=True))
    ticket = 'day-shift'
    edits = tuple(LabelEdit(10, row, 'N') for row in range(3))

    v1 = record_edits(database, ticket, parent, edits[:1])
    try:
        preview_correction(database, ticket, v1)
    except ValueError:
        pass
    else:
        raise RuntimeError('the overflowing draft should not preview')
    v2 = record_edits(database, ticket, parent, edits[1:2])
    preview_correction(database, ticket, v2)
    late = record_edits(database, ticket, parent, edits[2:3])
    stale_rejected = False
    try:
        sign_correction(database, ticket, v2)
    except ValueError:
        stale_rejected = True
    version, preview = preview_correction(database, ticket, late)

    attempted = []

    def interrupt(release_id):
        attempted.append(release_id)
        raise _Interrupted('night shift stopped before signature commit')

    interrupted = False
    try:
        sign_correction(database, ticket, version, before_commit=interrupt)
    except _Interrupted:
        interrupted = True
    rolled_back_absent = not _release_exists(database, attempted[0])
    initialize_store(database)
    signed = sign_correction(database, ticket, version)
    replay = sign_correction(database, ticket, version, before_commit=interrupt)
    closed = False
    try:
        record_edits(database, ticket, parent, edits[:1])
    except ValueError:
        closed = True

    page = read_page(database, signed, 10)
    second = read_page(database, signed, 4)
    extension = page.extensions[0]
    result = {
        'versions': [v1, v2, late],
        'stale_rejected': stale_rejected,
        'rolled_back': interrupted,
        'attempted_release_exists': not rolled_back_absent,
        'signed': signed,
        'replay_matches': replay == signed,
        'closed': closed,
        'preview_pages': [list(item) for item in preview],
        'page_order': [page.page_number, second.page_number],
        'labels': [row.label for row in page.observations[:3]],
        'extension': [extension.row_index, extension.raw.hex(), [list(ref) for ref in extension.references]],
        'totals': [row for row in _totals(database, signed) if row[0] in ('N', 'W')],
        'label_count': len(reconcile_release(database, signed)),
    }
    expected = {
        'versions': [1, 2, 3],
        'stale_rejected': True,
        'rolled_back': True,
        'attempted_release_exists': False,
        'signed': signed,
        'replay_matches': True,
        'closed': True,
        'page_order': [10, 4],
        'labels': ['N', 'N', 'N'],
        'extension': [256, '00ff', [[0, 'A']]],
    }
    if any(result[key] != expected[key] for key in expected) or result['totals'] != [['N', 3, 3, 3], ['W', 1, 1, 5]]:
        raise RuntimeError('ticket workflow demo differs from the hand-calculated handoff')
    print(f'更正单 {ticket}，版次 {version}，签发成果 {signed}，原固定成果 {parent}')
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': 'ticket_workflow',
        'input': {'source': 'full-page', 'ticket': ticket, 'parent': parent},
        'expected': {key: value for key, value in expected.items() if key != 'signed'},
        'actual': {key: value for key, value in result.items() if key != 'signed'},
        'preview_pages': result['preview_pages'],
        'totals': result['totals'],
        'label_count': result['label_count'],
        'code_paths': ['correction/request.py', 'correction/session.py', 'publication/commit.py', 'review/open_artifact.py', 'reconciliation/statement.py'],
        'oracle': 'Each batch adds one N edit; the pinned extension keeps slot zero on A. The third draft needs 255 slots, signs once and replays to the same release.',
    }, ensure_ascii=False, sort_keys=True))
    return True


def _release_exists(database, release_id: int) -> bool:
    try:
        read_receipt(database, release_id)
    except LookupError:
        return False
    return True


def demo() -> int:
    with TemporaryDirectory(prefix='instrument-handoff-demo-') as directory:
        database = Path(directory) / 'handoff.sqlite'
        initialize_store(database)
        _shift_demo(database)
    with TemporaryDirectory(prefix='instrument-ticket-demo-') as directory:
        database = Path(directory) / 'ticket.sqlite'
        initialize_store(database)
        _ticket_demo(database)
    return 0


def verify() -> int:
    suite = unittest.defaultTestLoader.discover(str(_ROOT / 'tests'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        return 1
    for mode in ('v1', 'workflow'):
        if ticket_examples.main([mode]) != 0:
            return 1
    print('更正单联合核验通过')
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='仪器交换包交班库')
    parser.add_argument('action', choices=('verify', 'demo'))
    args = parser.parse_args(argv)
    return demo() if args.action == 'demo' else verify()


if __name__ == '__main__':
    raise SystemExit(main())
