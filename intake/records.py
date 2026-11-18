from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceObservation:
    row_index: int
    slot: int
    reading: int | None


def parse_observation(fields: dict, row_index: int, dictionary: Mapping[int, str]) -> SourceObservation:
    if fields.keys() != {'kind', 'slot', 'reading'} or fields['kind'] != 'observation':
        raise ValueError('ordinary row must declare its slot and reading')
    slot = fields['slot']
    reading = fields['reading']
    if type(slot) is not int or slot not in dictionary:
        raise ValueError('ordinary row refers to an unassigned slot')
    if reading is not None and type(reading) is not int:
        raise ValueError('reading must be an integer or null')
    return SourceObservation(row_index, slot, reading)
