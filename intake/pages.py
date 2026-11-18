from dataclasses import dataclass

from intake.extensions import SourceExtension, parse_extension
from intake.records import SourceObservation, parse_observation
from publication.page_format import valid_page_number, valid_slot, valid_text


@dataclass(frozen=True)
class SourcePage:
    page_number: int
    dictionary: tuple[tuple[int, str], ...]
    rows: tuple[SourceObservation | SourceExtension, ...]


def _parse_dictionary(items) -> dict[int, str]:
    if not isinstance(items, list):
        raise ValueError('page dictionary must be a list of slot and label pairs')
    dictionary = {}
    for pair in items:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError('invalid page dictionary pair')
        slot, label = pair
        if not valid_slot(slot) or slot in dictionary or not valid_text(label):
            raise ValueError('invalid or duplicate page dictionary slot or label')
        dictionary[slot] = label
    return dictionary


def _parse_page(fields) -> SourcePage:
    if not isinstance(fields, dict) or fields.keys() != {'number', 'dictionary', 'rows'}:
        raise ValueError('page must declare number, dictionary and rows')
    number = fields['number']
    if not valid_page_number(number):
        raise ValueError('invalid page number')
    dictionary = _parse_dictionary(fields['dictionary'])
    if not isinstance(fields['rows'], list):
        raise ValueError(f'page {number} rows must be a list')
    rows = []
    for index, row in enumerate(fields['rows']):
        try:
            if not isinstance(row, dict):
                raise ValueError('row must be an object')
            kind = row.get('kind')
            if kind == 'observation':
                rows.append(parse_observation(row, index, dictionary))
            elif kind == 'extension':
                rows.append(parse_extension(row, index, dictionary))
            else:
                raise ValueError('unknown row kind')
        except ValueError as error:
            raise ValueError(f'page {number} row {index} has invalid data | {error}') from error
    return SourcePage(number, tuple(dictionary.items()), tuple(rows))


def parse_source_pages(items) -> tuple[SourcePage, ...]:
    if not isinstance(items, list) or not items:
        raise ValueError('package must contain at least one page')
    numbers = set()
    pages = []
    for fields in items:
        page = _parse_page(fields)
        if page.page_number in numbers:
            raise ValueError(f'duplicate page number {page.page_number}')
        numbers.add(page.page_number)
        pages.append(page)
    return tuple(pages)
