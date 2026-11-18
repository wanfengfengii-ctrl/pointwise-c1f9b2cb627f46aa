from sqlite3 import Connection

from publication.lineage import order_ancestral_pair
from publication.store import open_store
from reconciliation.groups import group_observations
from reconciliation.revision_diff import LabelDelta, diff_totals
from reconciliation.totals import LabelTotal
from review.open_artifact import iter_release_evidence


def _reconcile(connection: Connection, release_id: int) -> tuple[LabelTotal, ...]:
    observations = (
        observation
        for page in iter_release_evidence(connection, release_id)
        for observation in page.observations
    )
    return group_observations(observations)


def reconcile_release(database, release_id: int) -> tuple[LabelTotal, ...]:
    with open_store(database) as connection:
        return _reconcile(connection, release_id)


def compare_releases(database, first: int, second: int) -> tuple[LabelDelta, ...]:
    with open_store(database) as connection:
        older, newer = order_ancestral_pair(connection, first, second)
        old_totals = _reconcile(connection, older)
        new_totals = old_totals if older == newer else _reconcile(connection, newer)
        return diff_totals(old_totals, new_totals)
