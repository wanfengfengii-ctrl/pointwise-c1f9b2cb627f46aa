from hashlib import sha256

from correction.request import correct_labels
from correction.targets import LabelEdit
from intake.package import accept_package
from publication.catalog import PageNotFound, ReleaseNotFound
from publication.page_format import EncodedExtension, EncodedObservation, FixedPage, FixedPageError, encode_fixed_page
from publication.store import open_store
from reconciliation.statement import compare_releases, reconcile_release
from reconciliation.totals import LabelTotal
from review.extension_evidence import ExtensionEvidence
from review.observations import ObservationEvidence
from review.open_artifact import iter_release_evidence, read_page
from tests.fixtures import DatabaseCase, extension, observation, package, page


class NormalReview(DatabaseCase):
    def test_cold_pages(self):
        raw = package(
            page(10, [(0, 'N')], [observation(0, 7), extension('00ff', [0])]),
            page(4, [(0, 'W')], [extension('abcd', [0, 0]), observation(0, 5)]),
        )
        release = accept_package(self.database, 'cold', raw)
        del raw
        first = read_page(self.database, release, 10)
        second = read_page(self.database, release, 4)
        self.assertEqual(first.rows, (
            ObservationEvidence(10, 0, 'N', 7),
            ExtensionEvidence(10, 1, b'\x00\xff', ((0, 'N'),)),
        ))
        self.assertEqual(second.rows, (
            ExtensionEvidence(4, 0, b'\xab\xcd', ((0, 'W'), (0, 'W'))),
            ObservationEvidence(4, 1, 'W', 5),
        ))
        with open_store(self.database) as connection:
            self.assertEqual(tuple(iter_release_evidence(connection, release)), (first, second))
        self.assertEqual(reconcile_release(self.database, release), (
            LabelTotal('N', 1, 1, 7), LabelTotal('W', 1, 1, 5),
        ))

    def test_separate_releases(self):
        original = accept_package(self.database, 'one', package(page(1, [(0, 'A')], [observation(0, 7)])))
        revised = correct_labels(self.database, original, [LabelEdit(1, 0, 'N')])
        independent = accept_package(self.database, 'two', package(page(1, [(0, 'W')], [observation(0, 9)])))
        for release, label, reading in ((revised, 'N', 7), (independent, 'W', 9), (original, 'A', 7), (revised, 'N', 7)):
            evidence = read_page(self.database, release, 1)
            self.assertEqual(evidence.release_id, release)
            self.assertEqual(evidence.observations, (ObservationEvidence(1, 0, label, reading),))

    def test_extension_only_slot(self):
        raw = package(page(1, [(0, 'A'), (1, 'C'), (7, 'D')], [
            extension('00ff', [7, 0, 7]), observation(1, 7),
        ]))
        original = accept_package(self.database, 'ext-only', raw)
        revised = correct_labels(self.database, original, [LabelEdit(1, 1, 'N')])
        expected = ExtensionEvidence(1, 0, b'\x00\xff', ((7, 'D'), (0, 'A'), (7, 'D')))
        self.assertEqual(read_page(self.database, revised, 1).extensions, (expected,))
        self.assertEqual(read_page(self.database, original, 1).extensions, (expected,))
        self.assertEqual(reconcile_release(self.database, revised), (LabelTotal('N', 1, 1, 7),))

    def test_invalid_fixed_page(self):
        variants = {
            'missing body': None,
            'wrong digest': b'IPG1',
            'truncated structure': b'IPG1',
            'wrong page': encode_fixed_page(FixedPage(5, ((0, 'W'),), (EncodedObservation(0, 5),))),
            'missing ordinary slot': encode_fixed_page(FixedPage(4, ((0, 'W'),), (EncodedObservation(7, 5),))),
            'missing extension slot': encode_fixed_page(FixedPage(4, ((0, 'W'),), (EncodedExtension(b'\xff', (7,)),))),
        }
        for name, payload in variants.items():
            with self.subTest(name=name):
                original = self.accept_sample(name)
                child = correct_labels(self.database, original, [LabelEdit(10, 0, 'N')])
                with open_store(self.database) as connection:
                    if payload is None:
                        connection.execute('DELETE FROM fixed_pages WHERE release_id = ? AND page_no = 4', (original,))
                    else:
                        digest = bytes(32) if name == 'wrong digest' else sha256(payload).digest()
                        connection.execute(
                            'UPDATE fixed_pages SET payload = ?, digest = ? WHERE release_id = ? AND page_no = 4',
                            (payload, digest, original),
                        )
                self.assertEqual(read_page(self.database, original, 10).observations[0].label, 'A')
                self.assertEqual(read_page(self.database, child, 4).observations[0].label, 'W')
                with self.assertRaises(FixedPageError):
                    read_page(self.database, original, 4)
                with self.assertRaises(FixedPageError):
                    reconcile_release(self.database, original)
                with self.assertRaises(FixedPageError):
                    compare_releases(self.database, child, original)
                with self.assertRaises(PageNotFound):
                    read_page(self.database, original, 42)
        with self.assertRaises(ReleaseNotFound):
            read_page(self.database, 999, 10)
