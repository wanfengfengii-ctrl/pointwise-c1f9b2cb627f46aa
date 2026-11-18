from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from publication.page_format import EncodedObservation, FixedPage, valid_page_number, valid_text


class CorrectionTargetError(ValueError):
    """The batch does not select unique ordinary rows of the parent."""


@dataclass(frozen=True)
class LabelEdit:
    page_number: int
    row_index: int
    label: str


def bind_targets(
    pages: Mapping[int, FixedPage], edits: Iterable[LabelEdit]
) -> dict[int, dict[int, str]]:
    grouped = {}
    try:
        entries = iter(edits)
    except TypeError as error:
        raise CorrectionTargetError('an iterable of LabelEdit entries is required') from error
    for edit in entries:
        if not isinstance(edit, LabelEdit) or not valid_text(edit.label):
            raise CorrectionTargetError('each edit must give a coordinate and a nonempty label')
        number, index = edit.page_number, edit.row_index
        if not valid_page_number(number) or number not in pages:
            raise CorrectionTargetError(f'unknown correction page {number!r}')
        rows = pages[number].rows
        if type(index) is not int or not 0 <= index < len(rows):
            raise CorrectionTargetError(f'unknown physical row {index!r} on page {number}')
        if not isinstance(rows[index], EncodedObservation):
            raise CorrectionTargetError(f'page {number} row {index} is an extension')
        page_edits = grouped.setdefault(number, {})
        if index in page_edits:
            raise CorrectionTargetError(f'duplicate target on page {number} row {index}')
        page_edits[index] = edit.label
    if not grouped:
        raise CorrectionTargetError('a correction batch must contain at least one edit')
    return grouped
