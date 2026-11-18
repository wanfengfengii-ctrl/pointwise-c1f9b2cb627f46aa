"""Per-ticket draft state for the staged correction workflow."""

from dataclasses import dataclass
from hashlib import sha256
from sqlite3 import Connection

from correction.rewrite import rewrite_page, validate_parent_references
from correction.targets import LabelEdit, bind_targets
from publication.artifact import ArtifactPage, assemble_revision_pages
from publication.catalog import list_pages, load_page
from publication.page_format import (
    FixedPage,
    FixedPageError,
    decode_fixed_page_fields,
    encode_fixed_page,
    valid_text,
)


@dataclass(frozen=True)
class TicketState:
    ticket: str
    parent_id: int
    version: int
    closed: int


@dataclass(frozen=True)
class Signature:
    version: int
    release_id: int


def require_ticket(ticket) -> str:
    if not valid_text(ticket):
        raise ValueError('a correction ticket requires nonempty UTF-8 text')
    return ticket


def require_version(version) -> int:
    if type(version) is not int or version < 1:
        raise ValueError(f'invalid correction version {version!r}')
    return version


def load_ticket_state(connection: Connection, ticket: str) -> TicketState | None:
    row = connection.execute(
        'SELECT ticket, parent_id, version, closed FROM correction_tickets WHERE ticket = ?',
        (ticket,),
    ).fetchone()
    return None if row is None else TicketState(*row)


def load_signature(connection: Connection, ticket: str) -> Signature | None:
    row = connection.execute(
        'SELECT version, release_id FROM correction_signatures WHERE ticket = ?',
        (ticket,),
    ).fetchone()
    return None if row is None else Signature(*row)


def load_edits(connection: Connection, ticket: str) -> tuple[LabelEdit, ...]:
    rows = connection.execute(
        '''SELECT page_no, row_index, label FROM correction_edits
           WHERE ticket = ? ORDER BY page_no, row_index''',
        (ticket,),
    ).fetchall()
    return tuple(LabelEdit(*row) for row in rows)


def _decode_pages(connection: Connection, release_id: int) -> tuple[tuple[ArtifactPage, ...], dict[int, FixedPage]]:
    pages = tuple(
        load_page(connection, release_id, number) for number in list_pages(connection, release_id)
    )
    original = {}
    for item in pages:
        page = decode_fixed_page_fields(item.content)
        if page.page_number != item.page_number:
            raise FixedPageError(f'fixed content is for the wrong page at {item.page_number}')
        validate_parent_references(page)
        original[item.page_number] = page
    return pages, original


def build_candidate_pages(
    connection: Connection, parent_id: int, edits: tuple[LabelEdit, ...]
) -> tuple[ArtifactPage, ...]:
    """Rebuild the full fixed release for the current edit set using V1 rules."""
    pages, original = _decode_pages(connection, parent_id)
    targets = bind_targets(original, edits)
    replacements = {
        number: ArtifactPage(number, encode_fixed_page(rewrite_page(original[number], page_edits)))
        for number, page_edits in targets.items()
    }
    return assemble_revision_pages(pages, replacements)


def summarize_pages(pages: tuple[ArtifactPage, ...]) -> tuple[tuple[int, str], ...]:
    return tuple((page.page_number, sha256(page.content).hexdigest()) for page in pages)


def store_preview(
    connection: Connection, ticket: str, version: int, digests: tuple[tuple[int, str], ...]
) -> None:
    connection.execute(
        'DELETE FROM correction_previews WHERE ticket = ? AND version = ?', (ticket, version)
    )
    for ordinal, (page_no, digest) in enumerate(digests):
        connection.execute(
            '''INSERT INTO correction_previews (ticket, version, ordinal, page_no, digest)
               VALUES (?, ?, ?, ?, ?)''',
            (ticket, version, ordinal, page_no, digest),
        )


def load_preview(connection: Connection, ticket: str, version: int) -> tuple[tuple[int, str], ...]:
    rows = connection.execute(
        '''SELECT page_no, digest FROM correction_previews
           WHERE ticket = ? AND version = ? ORDER BY ordinal''',
        (ticket, version),
    ).fetchall()
    return tuple((page_no, digest) for page_no, digest in rows)


def discard_previews(connection: Connection, ticket: str) -> None:
    connection.execute('DELETE FROM correction_previews WHERE ticket = ?', (ticket,))
