from sqlite3 import Connection


class SourceConflict(ValueError):
    """An existing batch number was submitted with different source bytes."""


def match_source(connection: Connection, batch_no: str, raw: bytes) -> int | None:
    row = connection.execute(
        'SELECT payload, original_id FROM sources WHERE batch_no = ?', (batch_no,)
    ).fetchone()
    if row is None:
        return None
    original_bytes, original_id = row
    if raw != original_bytes:
        raise SourceConflict(f'source batch {batch_no!r} is already bound to different bytes')
    return original_id


def bind_source(connection: Connection, batch_no: str, raw: bytes, release_id: int) -> None:
    connection.execute(
        'INSERT INTO sources (batch_no, payload, original_id) VALUES (?, ?, ?)',
        (batch_no, raw, release_id),
    )
