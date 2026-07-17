import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app import invariants
from app.config import db_path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()


@contextmanager
def transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        invariants.check_invariants(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
