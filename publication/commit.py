from collections.abc import Callable, Sequence
from sqlite3 import Connection

from correction.session import (
    build_candidate_pages,
    load_edits,
    load_preview,
    load_signature,
    load_ticket_state,
    require_ticket,
    require_version,
    summarize_pages,
)
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


def _claim_release(
    connection: Connection,
    ticket: str,
    version: int,
    state,
    before_commit: Callable[[int], None] | None,
) -> int:
    """Persist the signed release, receipt and ticket binding in one transaction."""
    if load_signature(connection, ticket) is not None:
        raise ValueError(f'correction ticket {ticket!r} is already signed')
    if state.closed:
        raise ValueError(f'correction ticket {ticket!r} is closed after signature')
    if state.version != version:
        raise ValueError(f'ticket {ticket!r} is at version {state.version}, not {version}')

    preview = load_preview(connection, ticket, version)
    if not preview:
        raise ValueError(f'correction ticket {ticket!r} version {version} has no successful preview')
    pages = build_candidate_pages(connection, state.parent_id, load_edits(connection, ticket))
    if summarize_pages(pages) != preview:
        raise ValueError(f'correction ticket {ticket!r} version {version} differs from its preview')

    parent = find_release(connection, state.parent_id)
    release_id = _persist(connection, parent.batch_no, parent.release_id, pages)
    connection.execute(
        'INSERT INTO correction_signatures (ticket, version, release_id) VALUES (?, ?, ?)',
        (ticket, version, release_id),
    )
    connection.execute(
        'UPDATE correction_tickets SET closed = 1 WHERE ticket = ?', (ticket,)
    )
    if before_commit is not None:
        before_commit(release_id)
    return release_id


def sign_correction(
    database, ticket, version, *, before_commit: Callable[[int], None] | None = None
) -> int:
    """Sign the previewed current version of a ticket, releasing one child artifact."""
    ticket = require_ticket(ticket)
    version = require_version(version)
    with open_store(database) as connection, write_transaction(connection):
        signature = load_signature(connection, ticket)
        if signature is not None:
            if signature.version != version:
                raise ValueError(
                    f'correction ticket {ticket!r} is signed at version {signature.version}, not {version}'
                )
            return signature.release_id
        state = load_ticket_state(connection, ticket)
        if state is None:
            raise KeyError(ticket)
        return _claim_release(connection, ticket, version, state, before_commit)
