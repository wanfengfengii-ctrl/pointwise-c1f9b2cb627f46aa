from collections.abc import Mapping
from dataclasses import dataclass

from publication.page_format import EncodedExtension, FixedPageError


@dataclass(frozen=True)
class ExtensionEvidence:
    page_number: int
    row_index: int
    raw: bytes
    references: tuple[tuple[int, str], ...]


def decode_extension(
    page_number: int, row_index: int, row: EncodedExtension, dictionary: Mapping[int, str]
) -> ExtensionEvidence:
    references = []
    for slot in row.references:
        if slot not in dictionary:
            raise FixedPageError(f'page {page_number} extension at row {row_index} has unassigned slot {slot}')
        references.append((slot, dictionary[slot]))
    return ExtensionEvidence(page_number, row_index, row.raw, tuple(references))
