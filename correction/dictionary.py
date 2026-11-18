from collections.abc import Iterable
from dataclasses import dataclass

from publication.page_format import EncodedExtension, FixedPage, SLOT_COUNT


class PageCapacityError(ValueError):
    def __init__(self, page_number: int, required_slots: int):
        self.page_number = page_number
        self.required_slots = required_slots
        super().__init__(f'page {page_number} needs {required_slots} slots, capacity is {SLOT_COUNT}')


@dataclass(frozen=True)
class PageBinding:
    dictionary: tuple[tuple[int, str], ...]
    ordinary_slots: dict[str, int]


def allocate_page_dictionary(page: FixedPage, final_labels: Iterable[str]) -> PageBinding:
    old_slots = dict(page.dictionary)
    fixed_slots = {
        slot for row in page.rows if isinstance(row, EncodedExtension) for slot in row.references
    }
    slots = {slot: old_slots[slot] for slot in sorted(fixed_slots)}
    ordinary_slots = {}
    for slot, label in slots.items():
        ordinary_slots.setdefault(label, slot)

    final_order = dict.fromkeys(final_labels)
    required = len(slots) + len(final_order.keys() - ordinary_slots.keys())
    if required > SLOT_COUNT:
        raise PageCapacityError(page.page_number, required)

    # Keep one existing binding per surviving value where possible.
    for slot, label in sorted(old_slots.items()):
        if label in final_order and label not in ordinary_slots and slot not in slots:
            slots[slot] = label
            ordinary_slots[label] = slot

    available = (slot for slot in range(SLOT_COUNT) if slot not in slots)
    for label in final_order:
        if label not in ordinary_slots:
            slot = next(available)
            slots[slot] = label
            ordinary_slots[label] = slot
    return PageBinding(tuple(sorted(slots.items())), ordinary_slots)
