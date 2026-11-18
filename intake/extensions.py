from binascii import unhexlify
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceExtension:
    row_index: int
    raw: bytes
    references: tuple[int, ...]


def parse_extension(fields: dict, row_index: int, dictionary: Mapping[int, str]) -> SourceExtension:
    if fields.keys() != {'kind', 'hex', 'refs'} or fields['kind'] != 'extension':
        raise ValueError('extension must declare hex bytes and references')
    encoded = fields['hex']
    references = fields['refs']
    if not isinstance(encoded, str):
        raise ValueError('extension bytes must be hex text')
    raw = unhexlify(encoded)
    if not isinstance(references, list):
        raise ValueError('extension references must be a list')
    for slot in references:
        if type(slot) is not int or slot not in dictionary:
            raise ValueError('extension refers to an unassigned slot')
    return SourceExtension(row_index, raw, tuple(references))
