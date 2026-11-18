from collections.abc import Iterable

from reconciliation.totals import LabelTotal, TotalAccumulator
from review.observations import ObservationEvidence


def group_observations(observations: Iterable[ObservationEvidence]) -> tuple[LabelTotal, ...]:
    groups = {}
    for observation in observations:
        accumulator = groups.get(observation.label)
        if accumulator is None:
            accumulator = TotalAccumulator(observation.label)
            groups[observation.label] = accumulator
        accumulator.add(observation.reading)
    return tuple(groups[label].finish() for label in sorted(groups))
