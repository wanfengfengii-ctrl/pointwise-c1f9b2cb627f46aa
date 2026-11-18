import json

from correction.dictionary import PageCapacityError
from correction.request import correct_labels
from correction.targets import CorrectionTargetError, LabelEdit
from intake.package import accept_package
from publication.catalog import ReleaseNotFound, load_page
from publication.page_format import decode_fixed_page_fields
from publication.receipts import read_receipt
from publication.store import open_store
from reconciliation.statement import reconcile_release
from review.extension_evidence import ExtensionEvidence
from review.observations import ObservationEvidence
from review.open_artifact import read_page
from tests.fixtures import DatabaseCase, full_package


class NormalCorrection(DatabaseCase):
    def test_rebind_full_page(self):
        original = accept_package(self.database, 'full', full_package())
        revised = correct_labels(self.database, original, [LabelEdit(10, 0, 'N')])
        self.assertNotEqual(revised, original)
        self.assertEqual(read_receipt(self.database, revised).parent_id, original)
        new = read_page(self.database, revised, 10)
        old = read_page(self.database, original, 10)
        self.assertEqual(new.observations[0], ObservationEvidence(10, 0, 'N', 0))
        self.assertEqual(old.observations[0], ObservationEvidence(10, 0, 'A', 0))
        self.assertEqual(new.observations[1:], old.observations[1:])
        self.assertEqual(len(new.observations), 256)

    def test_joint_handoff(self):
        source = full_package()
        original = accept_package(self.database, 'joint', source)
        revised = correct_labels(self.database, original, [LabelEdit(10, 0, 'N')])
        del source
        actual = {}
        for version, release in (('new', revised), ('old', original)):
            first = read_page(self.database, release, 10)
            second = read_page(self.database, release, 4)
            self.assertEqual((first.page_number, second.page_number), (10, 4))
            self.assertEqual((len(first.rows), len(second.rows)), (256, 1))
            actual[version] = [
                [row.page_number, row.row_index, row.label, row.reading]
                for row in (first.observations[0], second.observations[0])
            ]
        expected = {'new': [[10, 0, 'N', 0], [4, 0, 'W', 5]], 'old': [[10, 0, 'A', 0], [4, 0, 'W', 5]]}
        self.assertEqual(actual, expected)
        totals = reconcile_release(self.database, revised)
        downstream_actual = [[row.label, row.records, row.non_null, row.net] for row in totals if row.label in {'A', 'N', 'W'}]
        downstream_expected = [['N', 1, 1, 0], ['W', 1, 1, 5]]
        self.assertEqual(downstream_actual, downstream_expected)
        self.assertEqual(len(totals), 257)
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'correct_ok.joint_handoff',
            'input': {'slots': 256, 'second_page_slot_zero': 'W', 'edit': [10, 0, 'N']},
            'expected': expected,
            'actual': actual,
            'downstream_expected': downstream_expected,
            'downstream_actual': downstream_actual,
            'code_paths': ['correction/request.py', 'correction/dictionary.py', 'publication/commit.py', 'review/decode_page.py', 'reconciliation/statement.py'],
            'oracle': 'Slot zero is used once on page 10. Replacing A leaves 256 labels there. Page 4 independently contributes one W with reading 5.',
        }, sort_keys=True))

    def test_reject_extension_target(self):
        original = self.accept_sample()
        prior = read_page(self.database, original, 10)
        receipt = read_receipt(self.database, original)
        counts = self.counts()
        with self.assertRaises(CorrectionTargetError):
            correct_labels(self.database, original, [LabelEdit(10, 0, 'N'), LabelEdit(10, 1, 'K')])
        self.assertEqual(read_page(self.database, original, 10), prior)
        self.assertEqual(read_receipt(self.database, original), receipt)
        self.assertEqual(self.counts(), counts)

    def test_interleaved_rows(self):
        original = self.accept_sample()
        revised = correct_labels(self.database, original, [LabelEdit(10, 2, 'Q')])
        evidence = read_page(self.database, revised, 10)
        self.assertEqual(evidence.rows, (
            ObservationEvidence(10, 0, 'A', 6),
            ExtensionEvidence(10, 1, b'\x00\xff', ((0, 'A'),)),
            ObservationEvidence(10, 2, 'Q', -6),
            ObservationEvidence(10, 3, 'M', None),
        ))

    def test_invalid_edits_leave_no_receipt(self):
        release = self.accept_sample()
        counts = self.counts()
        for edits in ([], [LabelEdit(10, 0, 'N')] * 2, [LabelEdit(99, 0, 'X')],
                      [LabelEdit(10, 4, 'X')], [LabelEdit(10, True, 'X')], [LabelEdit(10, 0, '')]):
            with self.subTest(edits=edits):
                with self.assertRaises(CorrectionTargetError):
                    correct_labels(self.database, release, edits)
        with self.assertRaises(ReleaseNotFound):
            correct_labels(self.database, 999, [LabelEdit(10, 0, 'N')])
        self.assertEqual(self.counts(), counts)

    def test_pinned_capacity(self):
        original = accept_package(self.database, 'pinned', full_package(pinned=True))
        counts = self.counts()
        old_first = read_page(self.database, original, 10)
        old_second = read_page(self.database, original, 4)
        receipt = read_receipt(self.database, original)
        with self.assertRaises(PageCapacityError) as failure:
            correct_labels(self.database, original, [LabelEdit(4, 0, 'Q'), LabelEdit(10, 0, 'N')])
        self.assertEqual((failure.exception.page_number, failure.exception.required_slots), (10, 257))
        self.assertEqual(self.counts(), counts)
        self.assertEqual(read_page(self.database, original, 10), old_first)
        self.assertEqual(read_page(self.database, original, 4), old_second)
        self.assertEqual(read_receipt(self.database, original), receipt)

        revised = correct_labels(self.database, original, [LabelEdit(10, 0, 'N'), LabelEdit(10, 1, 'T002')])
        evidence = read_page(self.database, revised, 10)
        self.assertEqual(evidence.observations[:3], (
            ObservationEvidence(10, 0, 'N', 0),
            ObservationEvidence(10, 1, 'T002', 1),
            ObservationEvidence(10, 2, 'T002', 2),
        ))
        self.assertEqual(evidence.observations[3:], old_first.observations[3:])
        self.assertEqual(evidence.extensions, (ExtensionEvidence(10, 256, b'\x00\xff', ((0, 'A'),)),))
        self.assertEqual(read_page(self.database, revised, 4).observations, old_second.observations)
        self.assertEqual(self.counts(), (1, 2, 4, 4, 2))

    def test_alias_rebind(self):
        original = accept_package(self.database, 'aliases', full_package(pinned=True, aliases=True))
        revised = correct_labels(self.database, original, [LabelEdit(10, 0, 'N')])
        with open_store(self.database) as connection:
            old_fixed = decode_fixed_page_fields(load_page(connection, original, 10).content)
            new_fixed = decode_fixed_page_fields(load_page(connection, revised, 10).content)
        self.assertEqual((old_fixed.rows[1].slot, old_fixed.rows[2].slot), (1, 2))
        self.assertEqual(new_fixed.rows[1].slot, new_fixed.rows[2].slot)
        self.assertEqual(len(new_fixed.dictionary), 256)
        evidence = read_page(self.database, revised, 10)
        self.assertEqual(evidence.observations[:3], (
            ObservationEvidence(10, 0, 'N', 0),
            ObservationEvidence(10, 1, 'B', 1),
            ObservationEvidence(10, 2, 'B', 2),
        ))
        self.assertEqual(evidence.extensions, (ExtensionEvidence(10, 256, b'\x00\xff', ((0, 'A'),)),))

    def test_equal_extension_values_pin_separate_slots(self):
        original = accept_package(self.database, 'pinned-aliases', full_package(pinned=True, aliases=True, pin_aliases=True))
        counts = self.counts()
        with self.assertRaises(PageCapacityError) as failure:
            correct_labels(self.database, original, [LabelEdit(10, 0, 'N')])
        self.assertEqual(failure.exception.required_slots, 257)
        evidence = read_page(self.database, original, 10)
        self.assertEqual(evidence.extensions[0].references, ((0, 'A'), (1, 'B'), (2, 'B')))
        self.assertEqual(self.counts(), counts)
