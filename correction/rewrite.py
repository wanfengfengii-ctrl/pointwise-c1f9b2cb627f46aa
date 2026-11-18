from collections.abc import Mapping

from correction.dictionary import allocate_page_dictionary
from publication.page_format import EncodedObservation, FixedPage, FixedPageError


def validate_parent_references(page: FixedPage) -> None:
    slots = dict(page.dictionary)
    for index, row in enumerate(page.rows):
        references = (row.slot,) if isinstance(row, EncodedObservation) else row.references
        if any(slot not in slots for slot in references):
            raise FixedPageError(f'page {page.page_number} row {index} refers to an unassigned slot')


def rewrite_page(page: FixedPage, edits: Mapping[int, str]) -> FixedPage:
    old_dictionary = dict(page.dictionary)
    final_labels = {
        index: edits.get(index, old_dictionary[row.slot])
        for index, row in enumerate(page.rows)
        if isinstance(row, EncodedObservation)
    }
    binding = allocate_page_dictionary(page, final_labels.values())
    rows = []
    for index, row in enumerate(page.rows):
        if isinstance(row, EncodedObservation):
            rows.append(EncodedObservation(binding.ordinary_slots[final_labels[index]], row.reading))
        else:
            rows.append(row)
    return FixedPage(page.page_number, binding.dictionary, tuple(rows))
