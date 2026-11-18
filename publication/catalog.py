from dataclasses import dataclass
from hashlib import sha256
from sqlite3 import Connection

from publication.artifact import ArtifactPage
from publication.page_format import FixedPageError, valid_page_number


class ReleaseNotFound(LookupError):
    """The requested release has not been published in this store."""


class PageNotFound(LookupError):
    """The requested page is outside the release directory."""


@dataclass(frozen=True)
class ReleaseEntry:
    release_id: int
    batch_no: str
    parent_id: int | None


def find_release(connection: Connection, release_id: int) -> ReleaseEntry:
    if type(release_id) is not int or not 1 <= release_id < 2 ** 63:
        raise ReleaseNotFound(f'unknown release {release_id!r}')
    row = connection.execute(
        'SELECT id, batch_no, parent_id FROM releases WHERE id = ?', (release_id,)
    ).fetchone()
    if row is None:
        raise ReleaseNotFound(f'unknown release {release_id}')
    return ReleaseEntry(*row)


def list_pages(connection: Connection, release_id: int) -> tuple[int, ...]:
    find_release(connection, release_id)
    rows = connection.execute(
        'SELECT ordinal, page_no FROM page_directory WHERE release_id = ? ORDER BY ordinal',
        (release_id,),
    ).fetchall()
    if not rows or any(i != row[0] for i, row in enumerate(rows)):
        raise FixedPageError(f'invalid page directory for release {release_id}')
    return tuple(number for _, number in rows)


def load_page(connection: Connection, release_id: int, page_number: int) -> ArtifactPage:
    if not valid_page_number(page_number):
        raise PageNotFound(f'unknown page {page_number!r} in release {release_id}')
    row = connection.execute(
        '''SELECT f.payload, f.digest
           FROM page_directory AS d
           LEFT JOIN fixed_pages AS f
             ON f.release_id = d.release_id AND f.page_no = d.page_no
           WHERE d.release_id = ? AND d.page_no = ?''',
        (release_id, page_number),
    ).fetchone()
    if row is None:
        raise PageNotFound(f'unknown page {page_number} in release {release_id}')
    payload, digest = row
    if not isinstance(payload, bytes) or digest != sha256(payload).digest():
        raise FixedPageError(f'missing or damaged fixed page {page_number} in release {release_id}')
    return ArtifactPage(page_number, payload)


def insert_release(connection: Connection, batch_no: str, parent_id: int | None) -> int:
    cursor = connection.execute(
        'INSERT INTO releases (batch_no, parent_id) VALUES (?, ?)', (batch_no, parent_id)
    )
    return cursor.lastrowid


def insert_page(connection: Connection, release_id: int, ordinal: int, page: ArtifactPage) -> None:
    connection.execute(
        'INSERT INTO page_directory (release_id, ordinal, page_no) VALUES (?, ?, ?)',
        (release_id, ordinal, page.page_number),
    )
    connection.execute(
        'INSERT INTO fixed_pages (release_id, page_no, payload, digest) VALUES (?, ?, ?, ?)',
        (release_id, page.page_number, page.content, sha256(page.content).digest()),
    )
