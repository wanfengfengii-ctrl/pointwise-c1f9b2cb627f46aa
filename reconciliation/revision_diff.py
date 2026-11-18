from collections.abc import Iterable
from dataclasses import dataclass

from reconciliation.totals import LabelTotal


@dataclass(frozen=True)
class LabelDelta:
    label: str
    records_delta: int
    non_null_delta: int
    net_delta: int | None


def diff_totals(old: Iterable[LabelTotal], new: Iterable[LabelTotal]) -> tuple[LabelDelta, ...]:
    earlier = {total.label: total for total in old}
    later = {total.label: total for total in new}
    changes = []
    for label in sorted(earlier.keys() | later.keys()):
        missing = LabelTotal(label, 0, 0, None)
        before = earlier.get(label, missing)
        after = later.get(label, missing)
        net_delta = None
        if before.non_null or after.non_null:
            net_delta = (after.net or 0) - (before.net or 0)
        changes.append(LabelDelta(
            label,
            after.records - before.records,
            after.non_null - before.non_null,
            net_delta,
        ))
    return tuple(changes)
