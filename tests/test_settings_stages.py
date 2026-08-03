"""Settings -> Stages: deletion is one-way (no restore, no undo), and the
up/down reorder arrows swap with the positionally-adjacent *active* row
rather than comparing raw rank values - a prior version of `move_stage`
compared `rank < ?` / `rank > ?` directly, which silently skipped over any
stage tied on rank (duplicates are possible - `stages.rank` has no unique
constraint) and could swap with a hidden inactive stage."""

from app import db


def _stage_id(name: str) -> int:
    conn = db.get_connection()
    row = conn.execute("SELECT id FROM stages WHERE name = ?", (name,)).fetchone()
    conn.close()
    return row["id"]


def _stage_rank(stage_id: int) -> int:
    conn = db.get_connection()
    row = conn.execute("SELECT rank FROM stages WHERE id = ?", (stage_id,)).fetchone()
    conn.close()
    return row["rank"]


def test_deleting_a_stage_removes_it_from_the_settings_list(client):
    stage_id = _stage_id("Fabric Received")
    client.post(f"/settings/stages/{stage_id}/delete", follow_redirects=True)

    conn = db.get_connection()
    row = conn.execute("SELECT active FROM stages WHERE id = ?", (stage_id,)).fetchone()
    conn.close()
    assert row["active"] == 0

    resp = client.get("/settings")
    assert "Fabric Received" not in resp.text


def test_deleting_a_stage_offers_no_undo(client):
    stage_id = _stage_id("Fabric Received")
    resp = client.post(f"/settings/stages/{stage_id}/delete", follow_redirects=True)
    assert "Undo" not in resp.text


def test_moving_first_stage_up_is_a_no_op(client):
    top_id = _stage_id("FI Done")  # rank 1, first in the list
    before = _stage_rank(top_id)

    client.post(f"/settings/stages/{top_id}/move", data={"direction": "up"}, follow_redirects=True)

    assert _stage_rank(top_id) == before


def test_moving_last_stage_down_is_a_no_op(client):
    bottom_id = _stage_id("Fabric Received")  # rank 13, last in the list
    before = _stage_rank(bottom_id)

    client.post(f"/settings/stages/{bottom_id}/move", data={"direction": "down"}, follow_redirects=True)

    assert _stage_rank(bottom_id) == before


def test_moving_never_swaps_with_an_inactive_neighbor(client):
    # "Under Cutting" (rank 8) sits directly above "Issued for Cutting" (rank 9).
    # Deactivate "Issued for Cutting", then moving "Under Cutting" down should
    # skip straight past it to "Bulk Pattern" (rank 10), not swap with the
    # now-hidden stage.
    under_cutting_id = _stage_id("Under Cutting")
    issued_for_cutting_id = _stage_id("Issued for Cutting")
    bulk_pattern_id = _stage_id("Bulk Pattern")

    client.post(f"/settings/stages/{issued_for_cutting_id}/delete", follow_redirects=True)

    under_cutting_before = _stage_rank(under_cutting_id)
    bulk_pattern_before = _stage_rank(bulk_pattern_id)
    issued_for_cutting_before = _stage_rank(issued_for_cutting_id)

    client.post(f"/settings/stages/{under_cutting_id}/move", data={"direction": "down"}, follow_redirects=True)

    # Under Cutting and Bulk Pattern swapped ranks with each other; the
    # deactivated stage in between was never touched.
    assert _stage_rank(under_cutting_id) == bulk_pattern_before
    assert _stage_rank(bulk_pattern_id) == under_cutting_before
    assert _stage_rank(issued_for_cutting_id) == issued_for_cutting_before


def test_moving_with_a_tied_rank_still_produces_a_correct_swap(client):
    # Force a duplicate rank, matching what the importer's STAGES-sheet sync can
    # produce in real data: make "Issued for Cutting" share rank 8 with
    # "Under Cutting" (instead of its normal rank 9).
    under_cutting_id = _stage_id("Under Cutting")
    issued_for_cutting_id = _stage_id("Issued for Cutting")
    bulk_pattern_id = _stage_id("Bulk Pattern")

    conn = db.get_connection()
    conn.execute("UPDATE stages SET rank = 8 WHERE id = ?", (issued_for_cutting_id,))
    conn.commit()
    conn.close()

    # Ordered by (rank, id): ... Under Cutting(8), Issued for Cutting(8, tied,
    # higher id so sorts after), Bulk Pattern(10) ...
    # Moving Bulk Pattern up should swap with its immediate predecessor in that
    # order - Issued for Cutting - not jump past the tie to Under Cutting.
    client.post(f"/settings/stages/{bulk_pattern_id}/move", data={"direction": "up"}, follow_redirects=True)

    assert _stage_rank(bulk_pattern_id) == 8  # took Issued for Cutting's old rank
    assert _stage_rank(issued_for_cutting_id) == 10  # took Bulk Pattern's old rank
    assert _stage_rank(under_cutting_id) == 8  # untouched
