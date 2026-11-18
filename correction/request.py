from collections.abc import Iterable

from correction.rewrite import rewrite_page, validate_parent_references
from correction.targets import LabelEdit, bind_targets
from publication.artifact import ArtifactPage, assemble_revision_pages
from publication.catalog import find_release, list_pages, load_page
from publication.commit import publish_revision
from publication.page_format import FixedPageError, decode_fixed_page_fields, encode_fixed_page
from publication.store import open_store


def correct_labels(database, parent_id: int, edits: Iterable[LabelEdit], *, before_commit=None) -> int:
    with open_store(database) as connection:
        parent = find_release(connection, parent_id)
        pages = tuple(
            load_page(connection, parent.release_id, number)
            for number in list_pages(connection, parent.release_id)
        )

    original = {}
    for item in pages:
        page = decode_fixed_page_fields(item.content)
        if page.page_number != item.page_number:
            raise FixedPageError(f'fixed content is for the wrong page at {item.page_number}')
        validate_parent_references(page)
        original[item.page_number] = page

    targets = bind_targets(original, edits)
    replacements = {}
    for number, page_edits in targets.items():
        final_page = rewrite_page(original[number], page_edits)
        replacements[number] = ArtifactPage(number, encode_fixed_page(final_page))
    fixed_pages = assemble_revision_pages(pages, replacements)
    return publish_revision(database, parent.release_id, fixed_pages, before_commit=before_commit)
