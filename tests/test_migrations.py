"""schema.sql intentionally has no roles table or password columns - migrations.py
is the sole source of the auth schema, applied on every boot (fresh install or an
upgrade of the real, already-populated database). A fresh db.init_db()+seed
connection IS exactly the "pre-migration" shape, since schema.sql never defines
these - so testing the migration is just: build that shape, run it, assert the
auth schema now exists and there's exactly one admin-capable user."""
from app import migrations


def test_fresh_seeded_db_has_no_auth_schema_yet(conn):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='roles'"
    ).fetchone()
    assert row is None
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    assert "password_hash" not in columns
    assert "role_id" not in columns


def test_run_migrations_adds_roles_table_and_user_columns(conn):
    migrations.run_migrations(conn)
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='roles'"
    ).fetchone()
    assert row is not None
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    assert {"password_hash", "password_salt", "role_id"} <= columns


def test_run_migrations_seeds_default_owner_role_with_all_bundles(conn):
    migrations.run_migrations(conn)
    role = conn.execute("SELECT * FROM roles WHERE name = 'Owner'").fetchone()
    assert role is not None
    assert role["can_move"] and role["can_edit"] and role["can_ship"] and role["can_admin"]


def test_run_migrations_leaves_exactly_one_admin_capable_user(conn):
    migrations.run_migrations(conn)
    admins = conn.execute(
        "SELECT u.name FROM users u JOIN roles r ON r.id = u.role_id "
        "WHERE r.can_admin = 1 AND u.active = 1"
    ).fetchall()
    assert len(admins) == 1
    assert admins[0]["name"] == "Owner"  # the seeded user, per seed.py's DEFAULT_USER


def test_run_migrations_is_idempotent(conn):
    migrations.run_migrations(conn)
    migrations.run_migrations(conn)  # must not raise (duplicate column/table, etc.)
    (role_count,) = conn.execute("SELECT COUNT(*) FROM roles").fetchone()
    assert role_count == 1  # didn't re-seed a second Owner role


def test_run_migrations_does_not_touch_existing_lot_data(conn, brand_ids, stage_ids, user_id):
    from app import operations

    lot_id = operations.create_lot(
        conn,
        brand_id=brand_ids["SPYKAR"],
        ct_number="A1",
        total_qty=500,
        starting_stage_id=stage_ids["Under Cutting"],
        moved_by=user_id,
    )
    migrations.run_migrations(conn)
    lot = conn.execute("SELECT * FROM lots WHERE id = ?", (lot_id,)).fetchone()
    assert lot["ct_number"] == "A1"
    assert lot["total_qty"] == 500


def test_run_migrations_promotes_first_active_user_when_seeded_user_renamed_or_gone(conn):
    # Simulate an upgrade path where the admin-capable user isn't literally named
    # "Owner" (e.g. renamed) - migration should still find *some* active user to
    # promote rather than leaving zero admins.
    conn.execute("UPDATE users SET name = 'Factory Owner' WHERE name = 'Owner'")
    conn.commit()
    migrations.run_migrations(conn)
    admins = conn.execute(
        "SELECT u.name FROM users u JOIN roles r ON r.id = u.role_id WHERE r.can_admin = 1 AND u.active = 1"
    ).fetchall()
    assert len(admins) == 1
    assert admins[0]["name"] == "Factory Owner"
