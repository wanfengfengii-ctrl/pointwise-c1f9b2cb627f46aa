import argparse
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from correction.request import correct_labels
from correction.targets import LabelEdit
from intake.package import accept_package
from publication.receipts import read_receipt
from publication.store import initialize_store
from reconciliation.statement import compare_releases, reconcile_release
from review.open_artifact import read_page

_ROOT = Path(__file__).resolve().parent


def _ordinary_rows(page):
    return [[row.row_index, row.label, row.reading] for row in page.observations]


def _totals(database, release):
    return [[row.label, row.records, row.non_null, row.net] for row in reconcile_release(database, release)]


def demo() -> int:
    with TemporaryDirectory(prefix='instrument-handoff-demo-') as directory:
        database = Path(directory) / 'handoff.sqlite'
        initialize_store(database)
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
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='仪器交换包交班库')
    parser.add_argument('action', choices=('verify', 'demo'))
    args = parser.parse_args(argv)
    if args.action == 'demo':
        return demo()
    suite = unittest.defaultTestLoader.discover(str(_ROOT / 'tests'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
