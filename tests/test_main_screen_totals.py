"""fetch_grouped_positions()'s ACR totals: ACR is a flat per-lot value (not
split-aware like stage_qty), so a lot split across two stages must count its
ACR once in each stage group's subtotal (it genuinely has pieces sitting in
both), but only once in the true grand total - otherwise a split lot's ACR
would be double-counted there. See the matching comment in main_screen.py."""

from app import operations
from app.routes.main_screen import fetch_grouped_positions


def _create_lot(conn, brand_ids, stage_ids, user_id, qty=1000, ct="A100"):
    return operations.create_lot(
        conn,
        brand_id=brand_ids["SPYKAR"],
        ct_number=ct,
        total_qty=qty,
        starting_stage_id=stage_ids["Under Cutting"],
        moved_by=user_id,
    )


def test_acr_subtotal_and_grand_total_for_an_unsplit_lot(conn, brand_ids, stage_ids, user_id):
    lot_id = _create_lot(conn, brand_ids, stage_ids, user_id, qty=1000)
    operations.update_lot_details(conn, lot_id=lot_id, acr=800)

    data = fetch_grouped_positions(conn, brand_id=None)
    group = next(g for g in data["groups"] if g["stage_name"] == "Under Cutting")
    assert group["acr_subtotal"] == 800
    assert data["acr_grand_total"] == 800


def test_acr_with_no_value_set_counts_as_zero(conn, brand_ids, stage_ids, user_id):
    _create_lot(conn, brand_ids, stage_ids, user_id, qty=1000)

    data = fetch_grouped_positions(conn, brand_id=None)
    group = next(g for g in data["groups"] if g["stage_name"] == "Under Cutting")
    assert group["acr_subtotal"] == 0
    assert data["acr_grand_total"] == 0


def test_split_lot_acr_appears_in_both_subtotals_but_once_in_grand_total(
    conn, brand_ids, stage_ids, user_id
):
    lot_id = _create_lot(conn, brand_ids, stage_ids, user_id, qty=1000)
    operations.update_lot_details(conn, lot_id=lot_id, acr=600)
    operations.move_pieces(
        conn, lot_id=lot_id, from_stage_id=stage_ids["Under Cutting"],
        to_stage_id=stage_ids["Under Sewing"], qty=400, moved_by=user_id,
    )

    data = fetch_grouped_positions(conn, brand_id=None)
    cutting = next(g for g in data["groups"] if g["stage_name"] == "Under Cutting")
    sewing = next(g for g in data["groups"] if g["stage_name"] == "Under Sewing")

    # Present in full in both stage groups it has pieces in...
    assert cutting["acr_subtotal"] == 600
    assert sewing["acr_subtotal"] == 600
    # ...but only counted once overall.
    assert data["acr_grand_total"] == 600


def test_grand_total_dedupes_across_multiple_split_lots(conn, brand_ids, stage_ids, user_id):
    lot_a = _create_lot(conn, brand_ids, stage_ids, user_id, qty=1000, ct="SPLITA")
    operations.update_lot_details(conn, lot_id=lot_a, acr=600)
    operations.move_pieces(
        conn, lot_id=lot_a, from_stage_id=stage_ids["Under Cutting"],
        to_stage_id=stage_ids["Under Sewing"], qty=400, moved_by=user_id,
    )

    lot_b = _create_lot(conn, brand_ids, stage_ids, user_id, qty=500, ct="WHOLE1")
    operations.update_lot_details(conn, lot_id=lot_b, acr=300)

    data = fetch_grouped_positions(conn, brand_id=None)
    assert data["acr_grand_total"] == 600 + 300
