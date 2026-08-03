import pytest

from app import auth, db
from tests.conftest import OWNER_TEST_PASSWORD


# --- Password hashing ---

def test_hash_and_verify_password_round_trip():
    password_hash, salt = auth.hash_password("correct horse battery staple")
    assert auth.verify_password("correct horse battery staple", password_hash, salt)


def test_verify_password_rejects_wrong_password():
    password_hash, salt = auth.hash_password("the-real-password")
    assert not auth.verify_password("a-guess", password_hash, salt)


def test_verify_password_handles_missing_hash_gracefully():
    assert not auth.verify_password("anything", None, None)


def test_same_password_different_salts_gives_different_hashes():
    hash_a, salt_a = auth.hash_password("same-password")
    hash_b, salt_b = auth.hash_password("same-password")
    assert salt_a != salt_b
    assert hash_a != hash_b


# --- Session signing ---

def test_sign_and_verify_session_round_trip():
    secret = b"a-fake-secret-key"
    token = auth.sign_session(42, secret)
    assert auth.verify_session(token, secret) == 42


def test_verify_session_rejects_tampered_payload():
    secret = b"a-fake-secret-key"
    token = auth.sign_session(42, secret)
    payload, _, signature = token.partition(".")
    tampered = f"999.{signature}"
    assert auth.verify_session(tampered, secret) is None


def test_verify_session_rejects_different_secret_simulating_restart():
    secret_a = b"secret-from-process-one"
    secret_b = b"secret-from-process-two-after-restart"
    token = auth.sign_session(42, secret_a)
    assert auth.verify_session(token, secret_b) is None


def test_verify_session_handles_garbage_gracefully():
    assert auth.verify_session(None, b"secret") is None
    assert auth.verify_session("not-a-real-token", b"secret") is None
    assert auth.verify_session("", b"secret") is None


# --- Setup + login HTTP flow ---

def _owner_user_id():
    conn = db.get_connection()
    row = conn.execute(
        "SELECT u.id FROM users u JOIN roles r ON r.id = u.role_id WHERE r.can_admin = 1"
    ).fetchone()
    conn.close()
    return row["id"]


def test_setup_then_login_round_trip(client):
    # `client` fixture already completed /setup; confirm a fresh client can log
    # back in with the same credentials (simulating a new browser session).
    owner_id = _owner_user_id()
    resp = client.post(
        "/login", data={"user_id": owner_id, "password": OWNER_TEST_PASSWORD, "next": "/"}
    )
    assert resp.status_code == 200  # followed the redirect to "/"
    assert "DPR" in resp.text or "Main" in resp.text


def test_login_wrong_password_is_rejected(client):
    owner_id = _owner_user_id()
    resp = client.post("/login", data={"user_id": owner_id, "password": "wrong-password", "next": "/"})
    assert "Incorrect username or password" in resp.text


def test_unauthenticated_request_redirects_to_login(client):
    client.cookies.clear()
    resp = client.get("/")
    assert resp.status_code == 200
    assert "DPR" in resp.text  # landed on the login page after the redirect
    assert "/login" in str(resp.url)


def test_restart_invalidates_session(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.web import create_app

    monkeypatch.setenv("DPR_DATA_DIR", str(tmp_path))
    app1 = create_app()
    with TestClient(app1) as client1:
        client1.post("/setup", data={"password": "pw12345", "password_confirm": "pw12345"})
        session_cookie = client1.cookies.get("dpr_session")
        assert session_cookie is not None

    # A new process (fresh secret key) must reject the old cookie.
    app2 = create_app()
    with TestClient(app2) as client2:
        client2.cookies.set("dpr_session", session_cookie)
        resp = client2.get("/", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"].startswith("/login")


# --- Permission gating ---

def _make_role(conn, name, **bundles):
    cur = conn.execute(
        "INSERT INTO roles (name, can_move, can_edit, can_ship, can_admin) VALUES (?, ?, ?, ?, ?)",
        (name, bundles.get("can_move", False), bundles.get("can_edit", False),
         bundles.get("can_ship", False), bundles.get("can_admin", False)),
    )
    conn.commit()
    return cur.lastrowid


def _make_user(conn, name, role_id, password):
    from app import auth as auth_module

    password_hash, salt = auth_module.hash_password(password)
    cur = conn.execute(
        "INSERT INTO users (name, role_id, password_hash, password_salt) VALUES (?, ?, ?, ?)",
        (name, role_id, password_hash, salt),
    )
    conn.commit()
    return cur.lastrowid


def _login_as(client, user_id, password):
    client.cookies.clear()
    resp = client.post("/login", data={"user_id": user_id, "password": password, "next": "/"})
    assert resp.status_code == 200
    return resp


def test_move_only_role_can_move_but_not_edit_or_settings(client):
    conn = db.get_connection()
    role_id = _make_role(conn, "Mover", can_move=True)
    user_id = _make_user(conn, "Mo", role_id, "mo-password")
    brand_id = conn.execute("SELECT id FROM brands WHERE name = 'SPYKAR'").fetchone()["id"]
    cutting_id = conn.execute("SELECT id FROM stages WHERE name = 'Under Cutting'").fetchone()["id"]
    sewing_id = conn.execute("SELECT id FROM stages WHERE name = 'Under Sewing'").fetchone()["id"]
    from app import operations
    lot_id = operations.create_lot(
        conn, brand_id=brand_id, ct_number="X1", total_qty=100, starting_stage_id=cutting_id
    )
    conn.close()

    _login_as(client, user_id, "mo-password")

    move_resp = client.post(
        f"/lots/{lot_id}/move",
        data={"from_stage_id": cutting_id, "to_stage_id": sewing_id, "qty": 100, "brand": ""},
        headers={"HX-Request": "true"},
    )
    assert move_resp.status_code == 200
    assert "Moved." in move_resp.text

    edit_resp = client.post(
        f"/lots/{lot_id}/edit",
        data={"remark": "trying to edit", "brand": ""},
        headers={"HX-Request": "true"},
    )
    assert edit_resp.status_code == 403
    assert "don&#39;t have permission" in edit_resp.text or "don't have permission" in edit_resp.text

    settings_resp = client.get("/settings")
    assert settings_resp.status_code == 403


def test_edit_only_role_cannot_ship(client):
    conn = db.get_connection()
    role_id = _make_role(conn, "Editor", can_edit=True)
    user_id = _make_user(conn, "Edie", role_id, "edie-password")
    brand_id = conn.execute("SELECT id FROM brands WHERE name = 'SPYKAR'").fetchone()["id"]
    fi_done_id = conn.execute("SELECT id FROM stages WHERE name = 'FI Done'").fetchone()["id"]
    from app import operations
    lot_id = operations.create_lot(
        conn, brand_id=brand_id, ct_number="X2", total_qty=50, starting_stage_id=fi_done_id
    )
    conn.close()

    _login_as(client, user_id, "edie-password")

    ship_resp = client.post(f"/lots/{lot_id}/ship", data={"brand": ""}, headers={"HX-Request": "true"})
    assert ship_resp.status_code == 403


def test_view_only_routes_open_to_any_logged_in_role(client):
    conn = db.get_connection()
    role_id = _make_role(conn, "Viewer")  # no bundles at all
    user_id = _make_user(conn, "Vic", role_id, "vic-password")
    conn.close()

    _login_as(client, user_id, "vic-password")
    assert client.get("/").status_code == 200
    assert client.get("/archive").status_code == 200
    assert client.get("/analytics").status_code == 200
    assert client.get("/settings").status_code == 403


def test_quit_requires_admin_permission(client):
    # A non-admin role must not be able to kill the shared server for everyone.
    conn = db.get_connection()
    role_id = _make_role(conn, "Mover2", can_move=True)
    user_id = _make_user(conn, "Mo2", role_id, "mo2-password")
    conn.close()

    _login_as(client, user_id, "mo2-password")
    resp = client.post("/quit")
    assert resp.status_code == 403


# --- Self-lockout guards ---

def test_cannot_remove_admin_bundle_from_last_admin_role(client):
    owner_id = _owner_user_id()
    conn = db.get_connection()
    role = conn.execute(
        "SELECT r.* FROM roles r JOIN users u ON u.role_id = r.id WHERE u.id = ?", (owner_id,)
    ).fetchone()
    conn.close()

    resp = client.post(
        f"/settings/roles/{role['id']}/update",
        data={"name": role["name"], "can_move": "true", "can_edit": "true", "can_ship": "true"},
        # can_admin omitted -> unchecked
        follow_redirects=True,
    )
    assert "leave no one able to manage Settings" in resp.text

    conn = db.get_connection()
    still_admin = conn.execute("SELECT can_admin FROM roles WHERE id = ?", (role["id"],)).fetchone()
    conn.close()
    assert still_admin["can_admin"] == 1  # unchanged


def test_cannot_deactivate_last_admin_user(client):
    owner_id = _owner_user_id()
    resp = client.post(f"/settings/users/{owner_id}/delete", follow_redirects=True)
    assert "leave no one able to manage Settings" in resp.text

    conn = db.get_connection()
    still_active = conn.execute("SELECT active FROM users WHERE id = ?", (owner_id,)).fetchone()
    conn.close()
    assert still_active["active"] == 1


def test_can_deactivate_admin_when_another_admin_exists(client):
    owner_id = _owner_user_id()
    conn = db.get_connection()
    owner_role_id = conn.execute("SELECT role_id FROM users WHERE id = ?", (owner_id,)).fetchone()["role_id"]
    second_admin_id = _make_user(conn, "Second Admin", owner_role_id, "second-pass")
    conn.close()

    resp = client.post(f"/settings/users/{owner_id}/delete", follow_redirects=True)
    assert "leave no one able to manage Settings" not in resp.text

    conn = db.get_connection()
    owner_now = conn.execute("SELECT active FROM users WHERE id = ?", (owner_id,)).fetchone()
    conn.close()
    assert owner_now["active"] == 0
