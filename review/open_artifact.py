from collections.abc import Iterator
from sqlite3 import Connection

from publication.catalog import find_release, list_pages, load_page
from publication.store import open_store
from review.decode_page import PageEvidence, decode_page


def _read_located_page(connection: Connection, release_id: int, page_number: int) -> PageEvidence:
    fixed = load_page(connection, release_id, page_number)
    return decode_page(release_id, page_number, fixed.content)


def read_page(database, release_id: int, page_number: int) -> PageEvidence:
    with open_store(database) as connection:
        find_release(connection, release_id)
        return _read_located_page(connection, release_id, page_number)


def iter_release_evidence(connection: Connection, release_id: int) -> Iterator[PageEvidence]:
    for page_number in list_pages(connection, release_id):
        yield _read_located_page(connection, release_id, page_number)
