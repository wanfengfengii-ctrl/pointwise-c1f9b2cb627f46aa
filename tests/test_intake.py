from correction.request import correct_labels
from correction.targets import LabelEdit
from intake.package import PackageError, accept_package, parse_package
from publication.receipts import Receipt, read_receipt
from publication.source_identity import SourceConflict
from publication.store import initialize_store, open_store
from review.extension_evidence import ExtensionEvidence
from review.observations import ObservationEvidence
from review.open_artifact import read_page
from tests.fixtures import DatabaseCase, extension, observation, package, page, sample_bytes


class NormalIntake(DatabaseCase):
    def test_original_page(self):
        raw = package(page(10, [(0, 'A')], [observation(0, 6), extension('00ff', [0, 0]), observation(0, None)]))
        source = parse_package('stand-7', raw)
        self.assertEqual(source.raw, raw)
        self.assertEqual([row.row_index for row in source.pages[0].rows], [0, 1, 2])
        release = accept_package(self.database, 'stand-7', raw)
        evidence = read_page(self.database, release, 10)
        self.assertEqual(evidence.rows, (
            ObservationEvidence(10, 0, 'A', 6),
            ExtensionEvidence(10, 1, b'\x00\xff', ((0, 'A'), (0, 'A'))),
            ObservationEvidence(10, 2, 'A', None),
        ))
        self.assertEqual(read_receipt(self.database, release), Receipt(release, 'stand-7', None))
        with open_store(self.database) as connection:
            stored = connection.execute('SELECT payload FROM sources WHERE batch_no = ?', ('stand-7',)).fetchone()
        self.assertEqual(stored, (raw,))
        self.assertEqual(self.counts(), (1, 1, 1, 1, 1))

    def test_missing_slot(self):
        for slot in (256, -1):
            with self.subTest(slot=slot):
                raw = package(page(1, [(0, 'A')], [extension('00ff', [slot])]))
                with self.assertRaises(PackageError):
                    accept_package(self.database, 'bad-extension', raw)
                self.assertEqual(self.counts(), (0, 0, 0, 0, 0))

    def test_unallocated_byte_slot(self):
        raw = package(page(1, [(0, 'A')], [observation(0, 7), extension('00ff', [7])]))
        with self.assertRaisesRegex(PackageError, 'unassigned slot'):
            accept_package(self.database, 'bad-membership', raw)
        self.assertEqual(self.counts(), (0, 0, 0, 0, 0))

    def test_malformed_source(self):
        valid = page(1, [(0, 'A')], [observation(0, 1)])
        malformed = (
            b'\xff',
            b'{"version":1,"version":1,"pages":[]}',
            b'{"version":true,"pages":[]}',
            package(),
            package(valid, valid),
            package(page(1, [(0, 'A'), (0, 'B')], [])),
            package(page(1, [(0, 'A')], [observation(3, 5)])),
            package(page(1, [(0, 'A')], [observation(0, True)])),
            package(page(1, [(0, 'A')], [observation(0, 1.0)])),
            package(page(1, [(0, 'A')], [extension('ff 00', [0])])),
        )
        for raw in malformed:
            with self.subTest(raw=raw):
                with self.assertRaises(PackageError):
                    accept_package(self.database, 'bad-package', raw)
        self.assertEqual(self.counts(), (0, 0, 0, 0, 0))

    def test_replay_and_conflict(self):
        raw = package(page(1, [(0, 'A')], [observation(0, 7)]))
        original = accept_package(self.database, 'stand-7', raw)
        receipt = read_receipt(self.database, original)
        self.assertEqual(accept_package(self.database, 'stand-7', raw), original)
        for different in (package(page(1, [(0, 'A')], [observation(0, 8)])), raw + b'\n'):
            with self.subTest(different=different):
                with self.assertRaises(SourceConflict):
                    accept_package(self.database, 'stand-7', different)
        self.assertEqual(read_page(self.database, original, 1).observations[0].reading, 7)
        self.assertEqual(read_receipt(self.database, original), receipt)
        self.assertEqual(self.counts(), (1, 1, 1, 1, 1))

    def test_reopen_initialize(self):
        raw = sample_bytes()
        original = accept_package(self.database, 'stand-8', raw)
        child = correct_labels(self.database, original, [LabelEdit(10, 0, 'N')])
        original_receipt = read_receipt(self.database, original)
        child_receipt = read_receipt(self.database, child)
        initialize_store(self.database)
        initialize_store(self.database)
        self.assertEqual(accept_package(self.database, 'stand-8', raw), original)
        with self.assertRaises(SourceConflict):
            accept_package(self.database, 'stand-8', raw + b'\n')
        self.assertEqual(read_receipt(self.database, original), original_receipt)
        self.assertEqual(read_receipt(self.database, child), child_receipt)
        self.assertEqual(child_receipt.parent_id, original)
        self.assertEqual(read_page(self.database, original, 10).observations[0].label, 'A')
        self.assertEqual(read_page(self.database, child, 10).observations[0].label, 'N')
        self.assertEqual(self.counts(), (1, 2, 4, 4, 2))
