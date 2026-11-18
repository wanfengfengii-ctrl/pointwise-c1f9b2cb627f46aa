from dataclasses import dataclass

from publication.page_format import EncodedObservation, FixedPageError, decode_fixed_page_fields
from review.extension_evidence import ExtensionEvidence, decode_extension
from review.observations import ObservationEvidence, decode_observation


@dataclass(frozen=True)
class PageEvidence:
    release_id: int
    page_number: int
    rows: tuple[ObservationEvidence | ExtensionEvidence, ...]

    @property
    def observations(self) -> tuple[ObservationEvidence, ...]:
        return tuple(row for row in self.rows if isinstance(row, ObservationEvidence))

    @property
    def extensions(self) -> tuple[ExtensionEvidence, ...]:
        return tuple(row for row in self.rows if isinstance(row, ExtensionEvidence))


def decode_page(release_id: int, page_number: int, content: bytes) -> PageEvidence:
    page = decode_fixed_page_fields(content)
    if page.page_number != page_number:
        raise FixedPageError(f'fixed content is for the wrong page at {page_number}')
    dictionary = dict(page.dictionary)
    rows = []
    for index, row in enumerate(page.rows):
        if isinstance(row, EncodedObservation):
            evidence = decode_observation(page_number, index, row, dictionary)
        else:
            evidence = decode_extension(page_number, index, row, dictionary)
        rows.append(evidence)
    return PageEvidence(release_id, page_number, tuple(rows))
