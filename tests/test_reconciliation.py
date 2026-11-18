from correction.request import correct_labels
from correction.targets import LabelEdit
from intake.package import accept_package
from publication.catalog import ReleaseNotFound
from publication.lineage import LineageError
from reconciliation.revision_diff import LabelDelta
from reconciliation.statement import compare_releases, reconcile_release
from reconciliation.totals import LabelTotal
from review.open_artifact import read_page
from tests.fixtures import DatabaseCase, observation, package, page


class NormalReconciliation(DatabaseCase):
    def test_labels_and_nulls(self):
        original = self.accept_sample()
        revised = correct_labels(self.database, original, [LabelEdit(10, 0, 'N')])
        self.assertEqual(reconcile_release(self.database, original), (
            LabelTotal('A', 2, 2, 0),
            LabelTotal('M', 1, 0, None),
            LabelTotal('W', 1, 1, 5),
        ))
        self.assertEqual(reconcile_release(self.database, revised), (
            LabelTotal('A', 1, 1, -6),
            LabelTotal('M', 1, 0, None),
            LabelTotal('N', 1, 1, 6),
            LabelTotal('W', 1, 1, 5),
        ))
        self.assertEqual(compare_releases(self.database, revised, original), (
            LabelDelta('A', -1, -1, -6),
            LabelDelta('M', 0, 0, None),
            LabelDelta('N', 1, 1, 6),
            LabelDelta('W', 0, 0, 0),
        ))
        moved = correct_labels(self.database, revised, [LabelEdit(10, 3, 'X')])
        differences = {row.label: row for row in compare_releases(self.database, revised, moved)}
        self.assertEqual(differences['M'], LabelDelta('M', -1, 0, None))
        self.assertEqual(differences['X'], LabelDelta('X', 1, 0, None))

    def test_precision(self):
        raw = package(
            page(10, [(0, 'Q'), (1, 'M')], [observation(0, 9007199254740993), observation(1, None)]),
            page(4, [(0, 'Q')], [observation(0, -9007199254740992)]),
        )
        original = accept_package(self.database, 'precision', raw)
        child = correct_labels(self.database, original, [LabelEdit(10, 0, 'R'), LabelEdit(4, 0, 'R')])
        self.assertEqual(read_page(self.database, original, 10).observations[0].reading, 9007199254740993)
        self.assertEqual(read_page(self.database, child, 4).observations[0].reading, -9007199254740992)
        totals = reconcile_release(self.database, original)
        self.assertEqual(totals, (LabelTotal('M', 1, 0, None), LabelTotal('Q', 2, 2, 1)))
        self.assertIs(type(totals[1].net), int)
        self.assertEqual(compare_releases(self.database, child, original), (
            LabelDelta('M', 0, 0, None), LabelDelta('Q', -2, -2, -1), LabelDelta('R', 2, 2, 1),
        ))

    def test_integer_wire_boundaries(self):
        raw = (
            b'{"version":1,"pages":[{"number":1,"dictionary":[[0,"Z"]],"rows":['
            b'{"kind":"observation","slot":0,"reading":1' + b'0' * 4500 + b'},'
            b'{"kind":"observation","slot":0,"reading":-' + b'9' * 4500 + b'}]}]}'
        )
        release = accept_package(self.database, 'very-wide', raw)
        first, second = read_page(self.database, release, 1).observations
        self.assertTrue(first.reading == 10 ** 4500)
        self.assertTrue(second.reading == 1 - 10 ** 4500)
        self.assertEqual(reconcile_release(self.database, release), (LabelTotal('Z', 2, 2, 1),))

    def test_ancestor_chain(self):
        root = self.accept_sample()
        child = correct_labels(self.database, root, [LabelEdit(10, 0, 'N')])
        sibling = correct_labels(self.database, root, [LabelEdit(10, 3, 'K')])
        grandchild = correct_labels(self.database, child, [LabelEdit(10, 2, 'N')])
        expected = (
            LabelDelta('A', -2, -2, 0),
            LabelDelta('M', 0, 0, None),
            LabelDelta('N', 2, 2, 0),
            LabelDelta('W', 0, 0, 0),
        )
        self.assertEqual(compare_releases(self.database, grandchild, root), expected)
        self.assertEqual(compare_releases(self.database, root, grandchild), expected)
        with self.assertRaises(LineageError):
            compare_releases(self.database, child, sibling)
        with self.assertRaises(LineageError):
            compare_releases(self.database, grandchild, sibling)
        other = self.accept_sample('another-source')
        with self.assertRaises(LineageError):
            compare_releases(self.database, other, grandchild)
        with self.assertRaises(ReleaseNotFound):
            compare_releases(self.database, root, 999)
        self.assertEqual(compare_releases(self.database, grandchild, grandchild), (
            LabelDelta('M', 0, 0, None), LabelDelta('N', 0, 0, 0), LabelDelta('W', 0, 0, 0),
        ))

    def test_codepoint_order_and_zero_record_count(self):
        raw = package(
            page(8, [(0, 'é'), (1, 'Z'), (2, 'e\u0301')], [observation(0, 0), observation(1, None), observation(2, 4)]),
            page(9, [], []),
        )
        original = accept_package(self.database, 'codepoints', raw)
        self.assertEqual(reconcile_release(self.database, original), (
            LabelTotal('Z', 1, 0, None), LabelTotal('e\u0301', 1, 1, 4), LabelTotal('é', 1, 1, 0),
        ))
        self.assertEqual(read_page(self.database, original, 9).rows, ())
