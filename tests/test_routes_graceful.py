"""HTTP-level regression tests for bugs found in real use:
- leaving the Brand filter on "Any" (which submits brand='') must not 422 on
  the main screen or the archive search
- archive search with only one field filled must still filter correctly
- partial (substring) material-code search must return matches
"""

from app import db, operations


def test_main_screen_with_blank_brand_param_does_not_error(client):
    resp = client.get("/?brand=")
    assert resp.status_code == 200


def test_main_screen_with_garbage_brand_param_does_not_error(client):
    resp = client.get("/?brand=not-a-number")
    assert resp.status_code == 200


def test_archive_with_blank_brand_param_does_not_error(client):
    resp = client.get("/archive?brand=")
    assert resp.status_code == 200


def test_archive_search_with_only_ct_filled(client):
    resp = client.get("/archive?ct=A5&brand=&code=&date_from=&date_to=")
    assert resp.status_code == 200


def test_archive_search_with_malformed_date_does_not_error(client):
    resp = client.get("/archive?date_from=not-a-date")
    assert resp.status_code == 200


def test_archive_search_partial_code_match(client):
    # client fixture already set DPR_DATA_DIR - open a connection to that same file
    # to seed a shipped lot directly, bypassing the HTTP layer.
    conn = db.get_connection()
    brand_id = conn.execute("SELECT id FROM brands WHERE name = 'SPYKAR'").fetchone()["id"]
    fi_done = conn.execute("SELECT id FROM stages WHERE name = 'FI Done'").fetchone()["id"]
    lot_id = operations.create_lot(
        conn,
        brand_id=brand_id,
        ct_number="Z999",
        total_qty=100,
        starting_stage_id=fi_done,
        material_code="EMDRO2BF011-HALFCODE",
    )
    operations.mark_shipped(conn, lot_id=lot_id)
    conn.close()

    resp = client.get("/archive?code=HALFCODE")
    assert resp.status_code == 200
    assert "Z999" in resp.text
