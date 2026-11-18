from correction.request import correct_labels
from correction.targets import LabelEdit
from intake.package import accept_package
from publication.catalog import ReleaseNotFound, list_pages, load_page
from publication.receipts import read_receipt
from publication.store import initialize_store, open_store
from review.open_artifact import read_page
from tests.fixtures import DatabaseCase, sample_bytes


class InterruptedPublication(RuntimeError):
    pass


class NormalPublication(DatabaseCase):
    def test_commit_failure(self):
        original = self.accept_sample()
        prior = read_page(self.database, original, 10)
        prior_receipt = read_receipt(self.database, original)
        counts = self.counts()
        attempted = []

        def interrupt(release_id):
            attempted.append(release_id)
            self.assertEqual(self.counts(), counts)
            with self.assertRaises(ReleaseNotFound):
                read_receipt(self.database, release_id)
            raise InterruptedPublication('operator interrupted release before commit')

        with self.assertRaises(InterruptedPublication):
            correct_labels(self.database, original, [LabelEdit(10, 0, 'N')], before_commit=interrupt)
        self.assertEqual(len(attempted), 1)
        initialize_store(self.database)
        self.assertEqual(self.counts(), counts)
        self.assertEqual(read_page(self.database, original, 10), prior)
        self.assertEqual(read_receipt(self.database, original), prior_receipt)
        with self.assertRaises(ReleaseNotFound):
            read_page(self.database, attempted[0], 10)
        with self.assertRaises(ReleaseNotFound):
            read_receipt(self.database, attempted[0])

    def test_failed_original_can_be_resubmitted(self):
        raw = sample_bytes()

        def interrupt(_release_id):
            raise InterruptedPublication('operator interrupted original before commit')

        with self.assertRaises(InterruptedPublication):
            accept_package(self.database, 'original', raw, before_commit=interrupt)
        self.assertEqual(self.counts(), (0, 0, 0, 0, 0))
        release = accept_package(self.database, 'original', raw)
        self.assertEqual(read_receipt(self.database, release).batch_no, 'original')
        self.assertEqual(accept_package(self.database, 'original', raw), release)
        self.assertEqual(self.counts(), (1, 1, 2, 2, 1))

    def test_unchanged_page_bytes_and_directory_order(self):
        original = self.accept_sample()
        revised = correct_labels(self.database, original, [LabelEdit(10, 0, 'N')])
        with open_store(self.database) as connection:
            self.assertEqual(list_pages(connection, original), (10, 4))
            self.assertEqual(list_pages(connection, revised), (10, 4))
            self.assertEqual(load_page(connection, original, 4), load_page(connection, revised, 4))
            self.assertNotEqual(load_page(connection, original, 10), load_page(connection, revised, 10))
        self.assertEqual(read_receipt(self.database, original).parent_id, None)
        self.assertEqual(read_receipt(self.database, revised).parent_id, original)
