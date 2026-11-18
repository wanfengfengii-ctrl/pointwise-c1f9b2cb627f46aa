from collections.abc import Callable, Sequence
from sqlite3 import Connection

from publication.artifact import ArtifactPage
from publication.catalog import find_release, insert_page, insert_release
from publication.receipts import Receipt, write_receipt
from publication.source_identity import bind_source, match_source
from publication.store import open_store, write_transaction


def _persist(
    connection: Connection, batch_no: str, parent_id: int | None, pages: Sequence[ArtifactPage]
) -> int:
    release_id = insert_release(connection, batch_no, parent_id)
    for ordinal, page in enumerate(pages):
        insert_page(connection, release_id, ordinal, page)
    write_receipt(connection, Receipt(release_id, batch_no, parent_id))
    return release_id


def publish_original(
    database,
    batch_no: str,
    raw: bytes,
    pages: Sequence[ArtifactPage],
    *,
    before_commit: Callable[[int], None] | None = None,
) -> int:
    with open_store(database) as connection, write_transaction(connection):
        existing = match_source(connection, batch_no, raw)
        if existing is not None:
            return existing
        release_id = _persist(connection, batch_no, None, pages)
        bind_source(connection, batch_no, raw, release_id)
        if before_commit is not None:
            before_commit(release_id)
    return release_id


def publish_revision(
    database,
    parent_id: int,
    pages: Sequence[ArtifactPage],
    *,
    before_commit: Callable[[int], None] | None = None,
) -> int:
    with open_store(database) as connection, write_transaction(connection):
        parent = find_release(connection, parent_id)
        release_id = _persist(connection, parent.batch_no, parent.release_id, pages)
        if before_commit is not None:
            before_commit(release_id)
    return release_id
