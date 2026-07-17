import pytest

from app import operations
from app.invariants import check_invariants


def _create_lot(conn, brand_ids, stage_ids, user_id, qty=1000, ct="A100"):
    return operations.create_lot(
        conn,
        brand_id=brand_ids["SPYKAR"],
        ct_number=ct,
        total_qty=qty,
        starting_stage_id=stage_ids["Under Cutting"],
        moved_by=user_id,
    )


def test_create_lot_opens_at_starting_stage(conn, brand_ids, stage_ids, user_id):
    lot_id = _create_lot(conn, brand_ids, stage_ids, user_id)
    positions = conn.execute(
        "SELECT * FROM positions WHERE lot_id = ?", (lot_id,)
    ).fetchall()
    assert len(positions) == 1
    assert positions[0]["qty"] == 1000
    movements = conn.execute(
        "SELECT * FROM movements WHERE lot_id = ?", (lot_id,)
    ).fetchall()
    assert len(movements) == 1
    assert movements[0]["from_stage_id"] is None
    check_invariants(conn)


def test_move_full_quantity(conn, brand_ids, stage_ids, user_id):
    lot_id = _create_lot(conn, brand_ids, stage_ids, user_id)
    operations.move_pieces(
        conn,
        lot_id=lot_id,
        from_stage_id=stage_ids["Under Cutting"],
        to_stage_id=stage_ids["Under Sewing"],
        qty=1000,
        moved_by=user_id,
    )
    positions = conn.execute(
        "SELECT * FROM positions WHERE lot_id = ?", (lot_id,)
    ).fetchall()
    assert len(positions) == 1
    assert positions[0]["stage_id"] == stage_ids["Under Sewing"]
    assert positions[0]["qty"] == 1000
    check_invariants(conn)


def test_split_move_creates_two_positions(conn, brand_ids, stage_ids, user_id):
    lot_id = _create_lot(conn, brand_ids, stage_ids, user_id, qty=1000)
    operations.move_pieces(
        conn,
        lot_id=lot_id,
        from_stage_id=stage_ids["Under Cutting"],
        to_stage_id=stage_ids["Under Sewing"],
        qty=500,
        moved_by=user_id,
    )
    positions = {
        p["stage_id"]: p["qty"]
        for p in conn.execute(
            "SELECT * FROM positions WHERE lot_id = ?", (lot_id,)
        ).fetchall()
    }
    assert positions[stage_ids["Under Cutting"]] == 500
    assert positions[stage_ids["Under Sewing"]] == 500
    check_invariants(conn)


def test_move_more_than_available_raises(conn, brand_ids, stage_ids, user_id):
    lot_id = _create_lot(conn, brand_ids, stage_ids, user_id, qty=300)
    with pytest.raises(operations.MoveError, match="Only 300 pieces are in"):
        operations.move_pieces(
            conn,
            lot_id=lot_id,
            from_stage_id=stage_ids["Under Cutting"],
            to_stage_id=stage_ids["Under Sewing"],
            qty=500,
            moved_by=user_id,
        )


def test_merge_keeps_earliest_entered_at(conn, brand_ids, stage_ids, user_id):
    lot_id = _create_lot(conn, brand_ids, stage_ids, user_id, qty=1000)
    # Move 500 first (this arrives at Under Sewing "early")
    operations.move_pieces(
        conn,
        lot_id=lot_id,
        from_stage_id=stage_ids["Under Cutting"],
        to_stage_id=stage_ids["Under Sewing"],
        qty=500,
        moved_by=user_id,
        moved_at="2026-01-01T00:00:00+00:00",
    )
    # Move remaining 500 later (arrives "late") - should merge, keeping earliest entered_at
    operations.move_pieces(
        conn,
        lot_id=lot_id,
        from_stage_id=stage_ids["Under Cutting"],
        to_stage_id=stage_ids["Under Sewing"],
        qty=500,
        moved_by=user_id,
        moved_at="2026-01-05T00:00:00+00:00",
    )
    position = conn.execute(
        "SELECT * FROM positions WHERE lot_id = ? AND stage_id = ?",
        (lot_id, stage_ids["Under Sewing"]),
    ).fetchone()
    assert position["qty"] == 1000
    assert position["entered_at"] == "2026-01-01T00:00:00+00:00"
    check_invariants(conn)


def test_undo_restores_prior_position(conn, brand_ids, stage_ids, user_id):
    lot_id = _create_lot(conn, brand_ids, stage_ids, user_id, qty=1000)
    movement_id = operations.move_pieces(
        conn,
        lot_id=lot_id,
        from_stage_id=stage_ids["Under Cutting"],
        to_stage_id=stage_ids["Under Sewing"],
        qty=1000,
        moved_by=user_id,
    )
    operations.undo_movement(conn, movement_id=movement_id, moved_by=user_id)
    positions = conn.execute(
        "SELECT * FROM positions WHERE lot_id = ?", (lot_id,)
    ).fetchall()
    assert len(positions) == 1
    assert positions[0]["stage_id"] == stage_ids["Under Cutting"]
    assert positions[0]["qty"] == 1000
    check_invariants(conn)


def test_undo_already_undone_raises(conn, brand_ids, stage_ids, user_id):
    lot_id = _create_lot(conn, brand_ids, stage_ids, user_id, qty=1000)
    movement_id = operations.move_pieces(
        conn,
        lot_id=lot_id,
        from_stage_id=stage_ids["Under Cutting"],
        to_stage_id=stage_ids["Under Sewing"],
        qty=1000,
        moved_by=user_id,
    )
    operations.undo_movement(conn, movement_id=movement_id, moved_by=user_id)
    with pytest.raises(operations.UndoError, match="already been undone"):
        operations.undo_movement(conn, movement_id=movement_id, moved_by=user_id)


def test_undo_blocked_when_pieces_moved_on(conn, brand_ids, stage_ids, user_id):
    lot_id = _create_lot(conn, brand_ids, stage_ids, user_id, qty=1000)
    movement_id = operations.move_pieces(
        conn,
        lot_id=lot_id,
        from_stage_id=stage_ids["Under Cutting"],
        to_stage_id=stage_ids["Under Sewing"],
        qty=1000,
        moved_by=user_id,
    )
    # pieces move on further before the first move is undone
    operations.move_pieces(
        conn,
        lot_id=lot_id,
        from_stage_id=stage_ids["Under Sewing"],
        to_stage_id=stage_ids["Under Washing"],
        qty=400,
        moved_by=user_id,
    )
    with pytest.raises(operations.UndoError, match="Undo the later moves first"):
        operations.undo_movement(conn, movement_id=movement_id, moved_by=user_id)


def test_undo_of_undo_is_allowed(conn, brand_ids, stage_ids, user_id):
    lot_id = _create_lot(conn, brand_ids, stage_ids, user_id, qty=1000)
    movement_id = operations.move_pieces(
        conn,
        lot_id=lot_id,
        from_stage_id=stage_ids["Under Cutting"],
        to_stage_id=stage_ids["Under Sewing"],
        qty=1000,
        moved_by=user_id,
    )
    undo_id = operations.undo_movement(conn, movement_id=movement_id, moved_by=user_id)
    # undoing the undo should be allowed and put pieces back in Under Sewing
    operations.undo_movement(conn, movement_id=undo_id, moved_by=user_id)
    position = conn.execute(
        "SELECT * FROM positions WHERE lot_id = ?", (lot_id,)
    ).fetchone()
    assert position["stage_id"] == stage_ids["Under Sewing"]
    assert position["qty"] == 1000
    check_invariants(conn)


def test_undo_opening_movement_with_no_others_deletes_lot(
    conn, brand_ids, stage_ids, user_id
):
    lot_id = _create_lot(conn, brand_ids, stage_ids, user_id, qty=1000)
    opening = conn.execute(
        "SELECT id FROM movements WHERE lot_id = ?", (lot_id,)
    ).fetchone()
    result = operations.undo_movement(conn, movement_id=opening["id"], moved_by=user_id)
    assert result is None
    remaining = conn.execute(
        "SELECT * FROM lots WHERE id = ?", (lot_id,)
    ).fetchone()
    assert remaining is None


def test_undo_opening_movement_blocked_when_later_moves_exist(
    conn, brand_ids, stage_ids, user_id
):
    lot_id = _create_lot(conn, brand_ids, stage_ids, user_id, qty=1000)
    operations.move_pieces(
        conn,
        lot_id=lot_id,
        from_stage_id=stage_ids["Under Cutting"],
        to_stage_id=stage_ids["Under Sewing"],
        qty=1000,
        moved_by=user_id,
    )
    opening = conn.execute(
        "SELECT id FROM movements WHERE lot_id = ? AND from_stage_id IS NULL",
        (lot_id,),
    ).fetchone()
    with pytest.raises(operations.UndoError, match="later movements exist"):
        operations.undo_movement(conn, movement_id=opening["id"], moved_by=user_id)


def test_mark_shipped_requires_all_pieces_at_fi_done(
    conn, brand_ids, stage_ids, user_id
):
    lot_id = _create_lot(conn, brand_ids, stage_ids, user_id, qty=1000)
    with pytest.raises(operations.MoveError, match="not fully at FI Done"):
        operations.mark_shipped(conn, lot_id=lot_id)

    operations.move_pieces(
        conn,
        lot_id=lot_id,
        from_stage_id=stage_ids["Under Cutting"],
        to_stage_id=stage_ids["FI Done"],
        qty=1000,
        moved_by=user_id,
    )
    operations.mark_shipped(conn, lot_id=lot_id)
    lot = conn.execute("SELECT closed_at FROM lots WHERE id = ?", (lot_id,)).fetchone()
    assert lot["closed_at"] is not None


def test_days_in_stage_current_and_historical(conn, brand_ids, stage_ids, user_id):
    lot_id = _create_lot(conn, brand_ids, stage_ids, user_id, qty=1000)
    operations.move_pieces(
        conn,
        lot_id=lot_id,
        from_stage_id=stage_ids["Under Cutting"],
        to_stage_id=stage_ids["Under Sewing"],
        qty=1000,
        moved_by=user_id,
    )
    current = operations.days_in_stage_current(conn, lot_id)
    assert len(current) == 1
    assert current[0]["stage_name"] == "Under Sewing"

    historical = operations.days_in_stage_historical(conn, lot_id)
    stage_names = {h["stage_name"] for h in historical}
    assert stage_names == {"Under Cutting", "Under Sewing"}
    cutting = next(h for h in historical if h["stage_name"] == "Under Cutting")
    assert cutting["last_left"] is not None
