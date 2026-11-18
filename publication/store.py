import sqlite3
from contextlib import contextmanager


_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS releases (
        id INTEGER PRIMARY KEY,
        batch_no TEXT NOT NULL REFERENCES sources(batch_no) DEFERRABLE INITIALLY DEFERRED,
        parent_id INTEGER REFERENCES releases(id)
    )''',
    '''CREATE TABLE IF NOT EXISTS sources (
        batch_no TEXT PRIMARY KEY NOT NULL,
        payload BLOB NOT NULL,
        original_id INTEGER UNIQUE NOT NULL REFERENCES releases(id)
    )''',
    '''CREATE TABLE IF NOT EXISTS page_directory (
        release_id INTEGER NOT NULL REFERENCES releases(id),
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        page_no INTEGER NOT NULL CHECK (page_no BETWEEN 1 AND 4294967295),
        PRIMARY KEY (release_id, page_no),
        UNIQUE (release_id, ordinal)
    )''',
    '''CREATE TABLE IF NOT EXISTS fixed_pages (
        release_id INTEGER NOT NULL,
        page_no INTEGER NOT NULL,
        payload BLOB NOT NULL,
        digest BLOB NOT NULL CHECK (length(digest) = 32),
        PRIMARY KEY (release_id, page_no),
        FOREIGN KEY (release_id, page_no) REFERENCES page_directory(release_id, page_no)
    )''',
    '''CREATE TABLE IF NOT EXISTS receipts (
        release_id INTEGER PRIMARY KEY REFERENCES releases(id),
        batch_no TEXT NOT NULL,
        parent_id INTEGER REFERENCES releases(id)
    )''',
)


@contextmanager
def open_store(database):
    connection = sqlite3.connect(database, isolation_level=None)
    try:
        connection.execute('PRAGMA foreign_keys = ON')
        yield connection
    finally:
        connection.close()


@contextmanager
def write_transaction(connection: sqlite3.Connection):
    connection.execute('BEGIN IMMEDIATE')
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def initialize_store(database) -> None:
    with open_store(database) as connection, write_transaction(connection):
        for statement in _SCHEMA:
            connection.execute(statement)
