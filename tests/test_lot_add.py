from app import db


def _stage_id(name: str) -> int:
    conn = db.get_connection()
    row = conn.execute("SELECT id FROM stages WHERE name = ?", (name,)).fetchone()
    conn.close()
    return row["id"]


def _brand_id(name: str) -> int:
    conn = db.get_connection()
    row = conn.execute("SELECT id FROM brands WHERE name = ?", (name,)).fetchone()
    conn.close()
    return row["id"]


def test_add_lot_via_import_page_redirects_with_undo(client):
    resp = client.post(
        "/lots/add",
        data={
            "brand_id": _brand_id("SPYKAR"),
            "ct_number": "NEW001",
            "total_qty": 500,
            "starting_stage_id": _stage_id("Under Cutting"),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/import?message=")
    assert "undo_url=" in resp.headers["location"]

    conn = db.get_connection()
    lot = conn.execute("SELECT * FROM lots WHERE ct_number = 'NEW001'").fetchone()
    conn.close()
    assert lot is not None
    assert lot["total_qty"] == 500


def test_add_lot_via_htmx_returns_panel_and_table_with_toast(client):
    resp = client.post(
        "/lots/add",
        data={
            "brand_id": _brand_id("SPYKAR"),
            "ct_number": "NEW002",
            "total_qty": 300,
            "starting_stage_id": _stage_id("Under Cutting"),
        },
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "NEW002" in resp.text
    assert "Added lot NEW002" in resp.text
    assert 'id="main-table-wrap"' in resp.text
    assert "hx-swap-oob" in resp.text


def test_add_lot_undo_removes_it(client):
    resp = client.post(
        "/lots/add",
        data={
            "brand_id": _brand_id("SPYKAR"),
            "ct_number": "NEW003",
            "total_qty": 200,
            "starting_stage_id": _stage_id("Under Cutting"),
        },
        headers={"HX-Request": "true"},
    )
    conn = db.get_connection()
    lot = conn.execute("SELECT id FROM lots WHERE ct_number = 'NEW003'").fetchone()
    movement = conn.execute(
        "SELECT id FROM movements WHERE lot_id = ?", (lot["id"],)
    ).fetchone()
    conn.close()

    undo_resp = client.post(
        f"/movements/{movement['id']}/undo",
        data={"lot_id": lot["id"], "brand": ""},
        headers={"HX-Request": "true"},
    )
    assert undo_resp.status_code == 200
    assert "Lot removed." in undo_resp.text

    conn = db.get_connection()
    remaining = conn.execute("SELECT * FROM lots WHERE ct_number = 'NEW003'").fetchone()
    conn.close()
    assert remaining is None
