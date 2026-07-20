import sqlite3

import pytest
from fastapi.testclient import TestClient

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


OWNER_TEST_PASSWORD = "test-owner-pass"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DPR_DATA_DIR", str(tmp_path))
    from app.web import create_app

    app = create_app()
    with TestClient(app) as test_client:
        # Complete first-run owner-password setup - the response also sets the
        # signed session cookie, logging this client in as the Owner (full
        # permissions), so existing route tests keep working unchanged.
        test_client.post(
            "/setup", data={"password": OWNER_TEST_PASSWORD, "password_confirm": OWNER_TEST_PASSWORD}
        )
        yield test_client
