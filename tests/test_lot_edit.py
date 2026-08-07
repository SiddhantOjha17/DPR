"""HTTP-level tests for the lot side panel's Edit form, specifically the Qty
and CT number fields - it's the same /lots/{id}/edit route used for
remark/fabric/etc., now also able to correct total_qty for a lot that isn't
split across stages, and to correct a lot's CT number."""

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


def _add_lot(client, ct_number, qty):
    client.post(
        "/lots/add",
        data={
            "brand_id": _brand_id("SPYKAR"),
            "ct_number": ct_number,
            "total_qty": qty,
            "starting_stage_id": _stage_id("Under Cutting"),
        },
        headers={"HX-Request": "true"},
    )
    conn = db.get_connection()
    lot_id = conn.execute("SELECT id FROM lots WHERE ct_number = ?", (ct_number,)).fetchone()["id"]
    conn.close()
    return lot_id


def test_editing_qty_via_the_panel_updates_lot_and_position(client):
    lot_id = _add_lot(client, "EDITQ1", 1000)

    resp = client.post(
        f"/lots/{lot_id}/edit",
        data={"total_qty": 850, "brand": ""},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "Saved." in resp.text

    conn = db.get_connection()
    lot = conn.execute("SELECT total_qty FROM lots WHERE id = ?", (lot_id,)).fetchone()
    position = conn.execute("SELECT qty FROM positions WHERE lot_id = ?", (lot_id,)).fetchone()
    conn.close()
    assert lot["total_qty"] == 850
    assert position["qty"] == 850


def test_editing_qty_undo_restores_the_original_value(client):
    lot_id = _add_lot(client, "EDITQ2", 1000)

    edit_resp = client.post(
        f"/lots/{lot_id}/edit",
        data={"total_qty": 850, "brand": ""},
        headers={"HX-Request": "true"},
    )
    assert 'name="total_qty" value="1000"' in edit_resp.text

    undo_resp = client.post(
        f"/lots/{lot_id}/edit",
        data={"total_qty": 1000, "brand": ""},
        headers={"HX-Request": "true"},
    )
    assert undo_resp.status_code == 200

    conn = db.get_connection()
    lot = conn.execute("SELECT total_qty FROM lots WHERE id = ?", (lot_id,)).fetchone()
    conn.close()
    assert lot["total_qty"] == 1000


def test_editing_qty_blocked_on_a_split_lot_shows_error(client):
    lot_id = _add_lot(client, "EDITQ3", 1000)
    client.post(
        f"/lots/{lot_id}/move",
        data={
            "from_stage_id": _stage_id("Under Cutting"),
            "to_stage_id": _stage_id("Under Sewing"),
            "qty": 500,
            "brand": "",
        },
        headers={"HX-Request": "true"},
    )

    resp = client.post(
        f"/lots/{lot_id}/edit",
        data={"total_qty": 750, "brand": ""},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "split across stages" in resp.text

    conn = db.get_connection()
    lot = conn.execute("SELECT total_qty FROM lots WHERE id = ?", (lot_id,)).fetchone()
    conn.close()
    assert lot["total_qty"] == 1000  # unchanged


def test_editing_ct_number_via_the_panel_updates_it(client):
    lot_id = _add_lot(client, "EDITCT1", 1000)

    resp = client.post(
        f"/lots/{lot_id}/edit",
        data={"ct_number": "EDITCT1-FIXED", "brand": ""},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "Saved." in resp.text

    conn = db.get_connection()
    lot = conn.execute("SELECT ct_number FROM lots WHERE id = ?", (lot_id,)).fetchone()
    conn.close()
    assert lot["ct_number"] == "EDITCT1-FIXED"


def test_editing_ct_number_to_an_existing_one_shows_error(client):
    _add_lot(client, "EDITCT2A", 500)
    lot_id = _add_lot(client, "EDITCT2B", 500)

    resp = client.post(
        f"/lots/{lot_id}/edit",
        data={"ct_number": "EDITCT2A", "brand": ""},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "already used" in resp.text

    conn = db.get_connection()
    lot = conn.execute("SELECT ct_number FROM lots WHERE id = ?", (lot_id,)).fetchone()
    conn.close()
    assert lot["ct_number"] == "EDITCT2B"  # unchanged


def test_leaving_ct_number_blank_does_not_touch_it(client):
    # An edit that only changes another field (e.g. remark) submits ct_number
    # blank too (nothing selected/typed) - that must mean "leave it as is",
    # not "clear the CT number".
    lot_id = _add_lot(client, "EDITCT3", 500)

    resp = client.post(
        f"/lots/{lot_id}/edit",
        data={"remark": "just a note", "brand": ""},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200

    conn = db.get_connection()
    lot = conn.execute("SELECT ct_number, remark FROM lots WHERE id = ?", (lot_id,)).fetchone()
    conn.close()
    assert lot["ct_number"] == "EDITCT3"
    assert lot["remark"] == "just a note"
