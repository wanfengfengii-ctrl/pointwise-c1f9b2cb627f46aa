from collections.abc import Iterable

from correction.rewrite import rewrite_page, validate_parent_references
from correction.session import (
    build_candidate_pages,
    discard_previews,
    load_edits,
    load_ticket_state,
    require_ticket,
    require_version,
    store_preview,
    summarize_pages,
)
from correction.targets import CorrectionTargetError, LabelEdit, bind_targets
from publication.artifact import ArtifactPage, assemble_revision_pages
from publication.catalog import find_release, list_pages, load_page
from publication.commit import publish_revision
from publication.page_format import FixedPageError, decode_fixed_page_fields, encode_fixed_page
from publication.store import open_store, write_transaction


def _decode_parent(connection, parent_id: int):
    pages = tuple(
        load_page(connection, parent_id, number) for number in list_pages(connection, parent_id)
    )
    original = {}
    for item in pages:
        page = decode_fixed_page_fields(item.content)
        if page.page_number != item.page_number:
            raise FixedPageError(f'fixed content is for the wrong page at {item.page_number}')
        validate_parent_references(page)
        original[item.page_number] = page
    return pages, original


def correct_labels(database, parent_id: int, edits: Iterable[LabelEdit], *, before_commit=None) -> int:
    with open_store(database) as connection:
        parent = find_release(connection, parent_id)
        pages, original = _decode_parent(connection, parent.release_id)

    targets = bind_targets(original, edits)
    replacements = {}
    for number, page_edits in targets.items():
        final_page = rewrite_page(original[number], page_edits)
        replacements[number] = ArtifactPage(number, encode_fixed_page(final_page))
    fixed_pages = assemble_revision_pages(pages, replacements)
    return publish_revision(database, parent.release_id, fixed_pages, before_commit=before_commit)


def _validated_batch(original, edits: Iterable[LabelEdit]) -> dict[int, dict[int, str]]:
    """Validate one intake batch against the fixed parent using the V1 target rules."""
    try:
        entries = tuple(edits)
    except TypeError as error:
        raise CorrectionTargetError('an iterable of LabelEdit entries is required') from error
    return bind_targets(original, entries)


def record_edits(database, ticket: str, parent_id: int, edits: Iterable[LabelEdit]) -> int:
    """Persist one intake batch and return the new draft version."""
    ticket = require_ticket(ticket)
    with open_store(database) as connection, write_transaction(connection):
        parent = find_release(connection, parent_id)
        _, original = _decode_parent(connection, parent.release_id)
        targets = _validated_batch(original, edits)

        state = load_ticket_state(connection, ticket)
        if state is None:
            connection.execute(
                'INSERT INTO correction_tickets (ticket, parent_id, version, closed) VALUES (?, ?, 1, 0)',
                (ticket, parent.release_id),
            )
            version = 1
        else:
            if state.parent_id != parent.release_id:
                raise ValueError(f'correction ticket {ticket!r} is fixed to parent {state.parent_id}')
            if state.closed:
                raise ValueError(f'correction ticket {ticket!r} is closed after signature')
            version = state.version + 1
            connection.execute(
                'UPDATE correction_tickets SET version = ? WHERE ticket = ?', (version, ticket)
            )

        for number, page_edits in targets.items():
            for index, label in page_edits.items():
                connection.execute(
                    '''INSERT INTO correction_edits (ticket, page_no, row_index, label)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT (ticket, page_no, row_index)
                       DO UPDATE SET label = excluded.label''',
                    (ticket, number, index, label),
                )
        discard_previews(connection, ticket)
    return version


def preview_correction(database, ticket: str, version: int) -> tuple[int, tuple[tuple[int, str], ...]]:
    """Trial-compute the current draft version without publishing anything."""
    ticket = require_ticket(ticket)
    version = require_version(version)
    with open_store(database) as connection, write_transaction(connection):
        state = load_ticket_state(connection, ticket)
        if state is None:
            raise KeyError(ticket)
        if state.closed:
            raise ValueError(f'correction ticket {ticket!r} is closed after signature')
        if state.version != version:
            raise ValueError(f'ticket {ticket!r} is at version {state.version}, not {version}')

        pages = build_candidate_pages(connection, state.parent_id, load_edits(connection, ticket))
        digests = summarize_pages(pages)
        store_preview(connection, ticket, version, digests)
    return version, digests
