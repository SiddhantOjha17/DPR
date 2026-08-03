"""Deleting a brand/role/user from Settings is one-way, same as stages
(test_settings_stages.py): it disappears from the list immediately and the
toast offers no "Undo". Self-lockout guards (can't remove the last
admin-capable role/user) must keep working under the renamed /delete routes."""

from app import db


def _brand_id(name: str) -> int:
    conn = db.get_connection()
    row = conn.execute("SELECT id FROM brands WHERE name = ?", (name,)).fetchone()
    conn.close()
    return row["id"]


def _owner_user_and_role_id() -> tuple[int, int]:
    conn = db.get_connection()
    row = conn.execute(
        "SELECT u.id AS user_id, r.id AS role_id FROM users u JOIN roles r ON r.id = u.role_id "
        "WHERE r.can_admin = 1"
    ).fetchone()
    conn.close()
    return row["user_id"], row["role_id"]


def test_deleting_a_brand_removes_it_and_offers_no_undo(client):
    brand_id = _brand_id("SPYKAR")
    resp = client.post(f"/settings/brands/{brand_id}/delete", follow_redirects=True)
    assert "Undo" not in resp.text

    conn = db.get_connection()
    active = conn.execute("SELECT active FROM brands WHERE id = ?", (brand_id,)).fetchone()["active"]
    conn.close()
    assert active == 0

    resp = client.get("/settings")
    assert "SPYKAR" not in resp.text


def test_deleting_a_non_admin_role_removes_it_and_offers_no_undo(client):
    conn = db.get_connection()
    cur = conn.execute("INSERT INTO roles (name, can_move) VALUES ('Mover', 1)")
    conn.commit()
    role_id = cur.lastrowid
    conn.close()

    resp = client.post(f"/settings/roles/{role_id}/delete", follow_redirects=True)
    assert "Undo" not in resp.text

    conn = db.get_connection()
    active = conn.execute("SELECT active FROM roles WHERE id = ?", (role_id,)).fetchone()["active"]
    conn.close()
    assert active == 0

    resp = client.get("/settings")
    assert "Mover" not in resp.text


def test_cannot_delete_the_last_admin_role(client):
    _, owner_role_id = _owner_user_and_role_id()
    resp = client.post(f"/settings/roles/{owner_role_id}/delete", follow_redirects=True)
    assert "leave no one able to manage Settings" in resp.text

    conn = db.get_connection()
    active = conn.execute("SELECT active FROM roles WHERE id = ?", (owner_role_id,)).fetchone()["active"]
    conn.close()
    assert active == 1  # unchanged


def test_deleting_a_non_admin_user_removes_them_and_offers_no_undo(client):
    conn = db.get_connection()
    cur = conn.execute("INSERT INTO users (name) VALUES ('Helper')")
    conn.commit()
    user_id = cur.lastrowid
    conn.close()

    resp = client.post(f"/settings/users/{user_id}/delete", follow_redirects=True)
    assert "Undo" not in resp.text

    conn = db.get_connection()
    active = conn.execute("SELECT active FROM users WHERE id = ?", (user_id,)).fetchone()["active"]
    conn.close()
    assert active == 0

    resp = client.get("/settings")
    assert "Helper" not in resp.text
