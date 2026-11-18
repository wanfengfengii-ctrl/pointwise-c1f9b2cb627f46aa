import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from intake.package import accept_package
from publication.store import initialize_store, open_store

_ROOT = Path(__file__).resolve().parents[1]


def observation(slot, reading):
    return {'kind': 'observation', 'slot': slot, 'reading': reading}


def extension(hex_bytes, references):
    return {'kind': 'extension', 'hex': hex_bytes, 'refs': list(references)}


def page(number, dictionary, rows):
    return {'number': number, 'dictionary': list(dictionary), 'rows': list(rows)}


def package(*pages):
    return json.dumps({'version': 1, 'pages': pages}, ensure_ascii=False).encode('utf-8')


def sample_bytes():
    return (_ROOT / 'samples' / 'shift.json').read_bytes()


def full_package(*, pinned=False, aliases=False, pin_aliases=False):
    spec = json.loads((_ROOT / 'tests' / 'data' / 'full-page.json').read_bytes())
    dictionary = [[0, spec['first_label']]]
    alias_slots = set(spec['alias_slots']) if aliases else set()
    for slot in range(1, spec['slot_count']):
        label = spec['alias_label'] if slot in alias_slots else f"{spec['label_prefix']}{slot:03d}"
        dictionary.append([slot, label])
    # One physical observation uses each slot. Its reading equals its slot.
    rows = [observation(slot, slot) for slot in range(spec['slot_count'])]
    if pinned:
        refs = spec['extension_slots'] + (sorted(alias_slots) if pin_aliases else [])
        rows.append(extension(spec['extension_hex'], refs))
    return package(
        page(spec['page_number'], dictionary, rows),
        page(spec['second_page_number'], [(0, spec['second_label'])], [observation(0, spec['second_reading'])]),
    )


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix='instrument-handoff-test-')
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / 'handoff.sqlite'
        initialize_store(self.database)

    def accept_sample(self, batch_no='shift-01'):
        return accept_package(self.database, batch_no, sample_bytes())

    def counts(self):
        with open_store(self.database) as connection:
            return tuple(
                connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                for table in ('sources', 'releases', 'page_directory', 'fixed_pages', 'receipts')
            )
