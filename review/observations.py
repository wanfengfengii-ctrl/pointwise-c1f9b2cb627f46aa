from collections.abc import Mapping
from dataclasses import dataclass

from publication.page_format import EncodedObservation, FixedPageError


@dataclass(frozen=True)
class ObservationEvidence:
    page_number: int
    row_index: int
    label: str
    reading: int | None


def decode_observation(
    page_number: int, row_index: int, row: EncodedObservation, dictionary: Mapping[int, str]
) -> ObservationEvidence:
    try:
        label = dictionary[row.slot]
    except KeyError as error:
        raise FixedPageError(f'page {page_number} row {row_index} has unassigned slot {row.slot}') from error
    return ObservationEvidence(page_number, row_index, label, row.reading)
