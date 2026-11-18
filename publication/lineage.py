from sqlite3 import Connection

from publication.catalog import ReleaseEntry, find_release


class LineageError(ValueError):
    """The two releases cannot be ordered on a single parent chain."""


def _has_ancestor(connection: Connection, descendant: ReleaseEntry, ancestor: int) -> bool:
    current = descendant
    visited = set()
    while current.release_id != ancestor:
        if current.release_id in visited:
            raise LineageError('cyclic release lineage')
        visited.add(current.release_id)
        if current.parent_id is None:
            return False
        parent = find_release(connection, current.parent_id)
        if parent.batch_no != descendant.batch_no:
            raise LineageError('source changed inside release lineage')
        current = parent
    return True


def order_ancestral_pair(connection: Connection, first: int, second: int) -> tuple[int, int]:
    left = find_release(connection, first)
    right = find_release(connection, second)
    if left.batch_no == right.batch_no:
        if _has_ancestor(connection, right, left.release_id):
            return left.release_id, right.release_id
        if _has_ancestor(connection, left, right.release_id):
            return right.release_id, left.release_id
    raise LineageError(f'releases {first} and {second} are on different parent chains')
