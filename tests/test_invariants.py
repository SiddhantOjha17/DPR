from datetime import datetime, timezone

import pytest

from app.invariants import InvariantViolation, check_invariants

NOW = datetime.now(timezone.utc).isoformat()


def _make_lot(conn, brand_ids, total_qty=1000):
    cur = conn.execute(
        "INSERT INTO lots (brand_id, ct_number, total_qty, created_at) "
        "VALUES (?, ?, ?, ?)",
        (brand_ids["SPYKAR"], "A100", total_qty, NOW),
    )
    return cur.lastrowid


def test_passes_when_positions_match_total(conn, brand_ids, stage_ids):
    lot_id = _make_lot(conn, brand_ids)
    conn.execute(
        "INSERT INTO positions (lot_id, stage_id, qty, entered_at) VALUES (?, ?, ?, ?)",
        (lot_id, stage_ids["Under Cutting"], 1000, NOW),
    )
    conn.commit()
    check_invariants(conn)  # should not raise


def test_passes_when_split_across_stages(conn, brand_ids, stage_ids):
    lot_id = _make_lot(conn, brand_ids)
    conn.execute(
        "INSERT INTO positions (lot_id, stage_id, qty, entered_at) VALUES (?, ?, ?, ?)",
        (lot_id, stage_ids["Under Washing"], 500, NOW),
    )
    conn.execute(
        "INSERT INTO positions (lot_id, stage_id, qty, entered_at) VALUES (?, ?, ?, ?)",
        (lot_id, stage_ids["Under Finishing"], 500, NOW),
    )
    conn.commit()
    check_invariants(conn)  # should not raise


def test_raises_when_positions_short_of_total(conn, brand_ids, stage_ids):
    lot_id = _make_lot(conn, brand_ids, total_qty=1000)
    conn.execute(
        "INSERT INTO positions (lot_id, stage_id, qty, entered_at) VALUES (?, ?, ?, ?)",
        (lot_id, stage_ids["Under Cutting"], 700, NOW),
    )
    conn.commit()
    with pytest.raises(InvariantViolation):
        check_invariants(conn)


def test_ignores_closed_lots(conn, brand_ids, stage_ids):
    cur = conn.execute(
        "INSERT INTO lots (brand_id, ct_number, total_qty, created_at, closed_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (brand_ids["SPYKAR"], "A101", 1000, NOW, NOW),
    )
    conn.commit()
    check_invariants(conn)  # closed lot has zero positions, but is excluded
