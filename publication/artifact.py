from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from intake.pages import SourcePage
from intake.records import SourceObservation
from publication.page_format import EncodedExtension, EncodedObservation, FixedPage, encode_fixed_page


@dataclass(frozen=True)
class ArtifactPage:
    page_number: int
    content: bytes


def encode_original_pages(source_pages: Sequence[SourcePage]) -> tuple[ArtifactPage, ...]:
    pages = []
    for source in source_pages:
        rows = []
        for row in source.rows:
            if isinstance(row, SourceObservation):
                rows.append(EncodedObservation(row.slot, row.reading))
            else:
                rows.append(EncodedExtension(row.raw, row.references))
        page = FixedPage(source.page_number, source.dictionary, tuple(rows))
        pages.append(ArtifactPage(source.page_number, encode_fixed_page(page)))
    return tuple(pages)


def assemble_revision_pages(
    originals: Sequence[ArtifactPage], replacements: Mapping[int, ArtifactPage]
) -> tuple[ArtifactPage, ...]:
    return tuple(replacements.get(page.page_number, page) for page in originals)
