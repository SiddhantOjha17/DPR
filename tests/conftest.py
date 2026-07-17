import sqlite3

import pytest

from app import db, seed


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    db.init_db(connection)
    seed.seed_if_empty(connection)
    yield connection
    connection.close()


@pytest.fixture
def stage_ids(conn):
    rows = conn.execute("SELECT id, name FROM stages").fetchall()
    return {row["name"]: row["id"] for row in rows}


@pytest.fixture
def brand_ids(conn):
    rows = conn.execute("SELECT id, name FROM brands").fetchall()
    return {row["name"]: row["id"] for row in rows}


@pytest.fixture
def user_id(conn):
    row = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
    return row["id"]
