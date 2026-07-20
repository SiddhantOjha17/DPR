"""Idempotent schema upgrades, safe to run on every boot against a database that
may already have real data in it (the original schema.sql's CREATE TABLE IF NOT
EXISTS only helps fresh installs - it does nothing to add new columns/tables to
an existing users table)."""
import sqlite3


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
        is not None
    )


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def run_migrations(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "roles"):
        conn.execute(
            """
            CREATE TABLE roles (
              id        INTEGER PRIMARY KEY,
              name      TEXT NOT NULL UNIQUE,
              can_move  INTEGER NOT NULL DEFAULT 0,
              can_edit  INTEGER NOT NULL DEFAULT 0,
              can_ship  INTEGER NOT NULL DEFAULT 0,
              can_admin INTEGER NOT NULL DEFAULT 0,
              active    INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.commit()

    for column, ddl in [
        ("password_hash", "ALTER TABLE users ADD COLUMN password_hash TEXT"),
        ("password_salt", "ALTER TABLE users ADD COLUMN password_salt TEXT"),
        ("role_id", "ALTER TABLE users ADD COLUMN role_id INTEGER REFERENCES roles(id)"),
    ]:
        if not _column_exists(conn, "users", column):
            conn.execute(ddl)
            conn.commit()

    (role_count,) = conn.execute("SELECT COUNT(*) FROM roles").fetchone()
    if role_count == 0:
        conn.execute(
            "INSERT INTO roles (name, can_move, can_edit, can_ship, can_admin) "
            "VALUES ('Owner', 1, 1, 1, 1)"
        )
        conn.commit()

    # Never leave the database with zero admin-capable users - if none exists,
    # promote the first unassigned user (the seeded "Owner" on a fresh install,
    # or the earliest-created user on an upgraded real database) into the
    # admin-capable role. Everyone else keeps role_id NULL (no permissions,
    # view-only) until the now-logged-in owner assigns them a role.
    admin_capable_exists = conn.execute(
        "SELECT 1 FROM users u JOIN roles r ON r.id = u.role_id "
        "WHERE r.can_admin = 1 AND u.active = 1 LIMIT 1"
    ).fetchone()
    if not admin_capable_exists:
        owner_role = conn.execute(
            "SELECT id FROM roles WHERE can_admin = 1 ORDER BY id LIMIT 1"
        ).fetchone()
        candidate = conn.execute(
            "SELECT id FROM users WHERE active = 1 ORDER BY id LIMIT 1"
        ).fetchone()
        if owner_role and candidate:
            conn.execute(
                "UPDATE users SET role_id = ? WHERE id = ?", (owner_role["id"], candidate["id"])
            )
            conn.commit()
