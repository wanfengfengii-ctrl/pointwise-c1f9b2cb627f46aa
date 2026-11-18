from dataclasses import dataclass
from sqlite3 import Connection

from publication.catalog import find_release
from publication.store import open_store


class ReceiptError(ValueError):
    """A published release is missing its recorded receipt or source binding."""


@dataclass(frozen=True)
class Receipt:
    release_id: int
    batch_no: str
    parent_id: int | None


def write_receipt(connection: Connection, receipt: Receipt) -> None:
    connection.execute(
        'INSERT INTO receipts (release_id, batch_no, parent_id) VALUES (?, ?, ?)',
        (receipt.release_id, receipt.batch_no, receipt.parent_id),
    )


def read_receipt(database, release_id: int) -> Receipt:
    with open_store(database) as connection:
        entry = find_release(connection, release_id)
        stored = connection.execute(
            'SELECT release_id, batch_no, parent_id FROM receipts WHERE release_id = ?',
            (entry.release_id,),
        ).fetchone()
        if stored != (entry.release_id, entry.batch_no, entry.parent_id):
            raise ReceiptError(f'missing or inconsistent receipt for release {release_id}')
    return Receipt(*stored)
