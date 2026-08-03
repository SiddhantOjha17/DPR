"""Settings -> Stages: deletion is one-way (no restore, no undo), and the
up/down reorder arrows always produce a correct, visible move.

A prior version of `move_stage` swapped stored *rank values* between the
clicked stage and its neighbor. That silently no-ops whenever the two ranks
being swapped are already equal (real data has ties - see the STAGES-sheet
import: "Under Cutting"/"Issued for Cutting" both landed on rank 10) - since
swapping two equal values changes nothing, and the tiebreak (`id`) never
changes either, the two rows' relative order was permanently stuck no matter
how many times the arrow was clicked. The fix swaps list *positions* instead
and renumbers the whole active list to clean 1..N ranks, so order always
changes correctly regardless of what the underlying rank values were."""

from app import db


def _stage_id(name: str) -> int:
    conn = db.get_connection()
    row = conn.execute("SELECT id FROM stages WHERE name = ?", (name,)).fetchone()
    conn.close()
    return row["id"]


def _active_order() -> list[str]:
    conn = db.get_connection()
    rows = conn.execute("SELECT name FROM stages WHERE active = 1 ORDER BY rank, id").fetchall()
    conn.close()
    return [row["name"] for row in rows]


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
    before = _active_order()
    top_id = _stage_id(before[0])

    client.post(f"/settings/stages/{top_id}/move", data={"direction": "up"}, follow_redirects=True)

    assert _active_order() == before


def test_moving_last_stage_down_is_a_no_op(client):
    before = _active_order()
    bottom_id = _stage_id(before[-1])

    client.post(f"/settings/stages/{bottom_id}/move", data={"direction": "down"}, follow_redirects=True)

    assert _active_order() == before


def test_moving_never_swaps_with_an_inactive_neighbor(client):
    # "Under Cutting" sits directly above "Issued for Cutting". Deactivate
    # "Issued for Cutting", then moving "Under Cutting" down should skip
    # straight past it to "Bulk Pattern", not swap with the now-hidden stage.
    under_cutting_id = _stage_id("Under Cutting")
    issued_for_cutting_id = _stage_id("Issued for Cutting")

    client.post(f"/settings/stages/{issued_for_cutting_id}/delete", follow_redirects=True)
    before = _active_order()
    assert "Issued for Cutting" not in before  # deactivated, invisible to reordering

    client.post(f"/settings/stages/{under_cutting_id}/move", data={"direction": "down"}, follow_redirects=True)

    after = _active_order()
    # Under Cutting swapped with whatever came after it (Bulk Pattern) -
    # everything else's relative order is unchanged.
    ucb, bpb = before.index("Under Cutting"), before.index("Under Cutting") + 1
    assert after[ucb] == before[bpb]
    assert after[bpb] == before[ucb]
    assert after[:ucb] == before[:ucb]
    assert after[bpb + 1:] == before[bpb + 1:]


def test_moving_with_a_tied_rank_still_produces_a_correct_swap(client):
    # Force a duplicate rank, matching what the importer's STAGES-sheet sync can
    # produce in real data: make "Issued for Cutting" share a rank with
    # "Under Cutting".
    under_cutting_id = _stage_id("Under Cutting")
    issued_for_cutting_id = _stage_id("Issued for Cutting")

    conn = db.get_connection()
    under_cutting_rank = conn.execute(
        "SELECT rank FROM stages WHERE id = ?", (under_cutting_id,)
    ).fetchone()["rank"]
    conn.execute("UPDATE stages SET rank = ? WHERE id = ?", (under_cutting_rank, issued_for_cutting_id))
    conn.commit()
    conn.close()

    before = _active_order()
    assert before.index("Under Cutting") + 1 == before.index("Issued for Cutting")

    bulk_pattern_id = _stage_id("Bulk Pattern")
    client.post(f"/settings/stages/{bulk_pattern_id}/move", data={"direction": "up"}, follow_redirects=True)
    after = _active_order()
    assert after.index("Bulk Pattern") == before.index("Bulk Pattern") - 1


def test_moving_a_stage_past_its_own_rank_tied_twin_actually_moves_it(client):
    # The exact bug this test guards against: two stages tied on the *same*
    # rank, clicking the arrow to swap them with each other specifically
    # (not with a third, distinctly-ranked stage) must still visibly reorder
    # them - swapping two equal rank values is a no-op, so this only passes
    # if the fix swaps by list position instead of by rank value.
    under_cutting_id = _stage_id("Under Cutting")
    issued_for_cutting_id = _stage_id("Issued for Cutting")

    conn = db.get_connection()
    under_cutting_rank = conn.execute(
        "SELECT rank FROM stages WHERE id = ?", (under_cutting_id,)
    ).fetchone()["rank"]
    conn.execute("UPDATE stages SET rank = ? WHERE id = ?", (under_cutting_rank, issued_for_cutting_id))
    conn.commit()
    conn.close()

    before = _active_order()
    assert before.index("Under Cutting") + 1 == before.index("Issued for Cutting")

    client.post(f"/settings/stages/{issued_for_cutting_id}/move", data={"direction": "up"}, follow_redirects=True)

    after = _active_order()
    assert after.index("Issued for Cutting") + 1 == after.index("Under Cutting")
