from pathlib import Path

from app.importer import EXPECTED_PER_BRAND, EXPECTED_TOTAL_LOTS, EXPECTED_TOTAL_PIECES, import_workbook
from app.invariants import check_invariants

FIXTURE = Path(__file__).parent / "fixtures" / "june_dpr.xlsx"


def test_import_reconciles_to_expected_totals(conn):
    result = import_workbook(str(FIXTURE), conn)

    assert result.total_lots == EXPECTED_TOTAL_LOTS == 135
    assert result.total_pieces == EXPECTED_TOTAL_PIECES == 90908
    assert result.per_brand == EXPECTED_PER_BRAND
    assert result.unmapped_statuses == []


def test_import_preserves_invariant(conn):
    import_workbook(str(FIXTURE), conn)
    check_invariants(conn)  # should not raise


def test_import_keeps_original_status_text_in_remark(conn):
    import_workbook(str(FIXTURE), conn)
    row = conn.execute(
        "SELECT remark FROM lots WHERE ct_number = 'A539'"
    ).fetchone()
    assert row is not None
    assert row["remark"].strip().lower() == "under finishing"


def test_raymond_sub_brands_assigned_from_brand_column(conn):
    import_workbook(str(FIXTURE), conn)
    rows = conn.execute(
        "SELECT l.ct_number, sb.name FROM lots l "
        "JOIN brands b ON b.id = l.brand_id "
        "JOIN sub_brands sb ON sb.id = l.sub_brand_id "
        "WHERE b.name = 'RAYMOND'"
    ).fetchall()
    assert len(rows) > 0
    names = {r["name"] for r in rows}
    assert names <= {"CP", "PARX", "PA"}


def test_arvind_brand_column_not_treated_as_sub_brand(conn):
    import_workbook(str(FIXTURE), conn)
    row = conn.execute(
        "SELECT sub_brand_id FROM lots l JOIN brands b ON b.id = l.brand_id "
        "WHERE b.name = 'ARVIND' LIMIT 1"
    ).fetchone()
    assert row["sub_brand_id"] is None


def test_spykar_wash_column_populated(conn):
    import_workbook(str(FIXTURE), conn)
    row = conn.execute(
        "SELECT wash FROM lots l JOIN brands b ON b.id = l.brand_id "
        "WHERE b.name = 'SPYKAR' AND wash IS NOT NULL LIMIT 1"
    ).fetchone()
    assert row is not None


def test_reimporting_same_file_skips_rows_with_a_real_ct_number(conn):
    first = import_workbook(str(FIXTURE), conn)
    assert first.total_lots == 135

    second = import_workbook(str(FIXTURE), conn)
    # Every ARVIND row has a blank CT number in the real sheet (confirmed by direct
    # inspection) - those can never be deduplicated, since there's nothing to match
    # on, so they legitimately reappear as "new" on a second import. Every row that
    # DOES have a real CT number must be skipped instead of duplicated.
    skipped_cts = {ct for _, ct in second.skipped_duplicates}
    assert "A539" in skipped_cts  # a real CT from the RAYMOND sheet
    assert "B017" in skipped_cts  # a real CT from the MONTE CARLO sheet
    assert second.per_brand["RAYMOND"] == 0  # RAYMOND CTs are all real -> all skipped
    assert second.per_brand["ARVIND"] == 10700  # ARVIND CTs are all blank -> all re-added

    (total_lots,) = conn.execute("SELECT COUNT(*) FROM lots").fetchone()
    assert total_lots == 135 + second.total_lots
    check_invariants(conn)


def test_blank_ct_rows_are_never_treated_as_duplicates_of_each_other(conn):
    result = import_workbook(str(FIXTURE), conn)
    # ARVIND has several legitimate rows with a blank CT number - none of them
    # should be skipped as "duplicates" of one another.
    blank_ct_skips = [s for s in result.skipped_duplicates if s[1] == ""]
    assert blank_ct_skips == []


def test_replace_mode_wipes_existing_lots_first(conn):
    import_workbook(str(FIXTURE), conn)
    (before,) = conn.execute("SELECT COUNT(*) FROM lots").fetchone()
    assert before == 135

    result = import_workbook(str(FIXTURE), conn, wipe_existing=True)
    assert result.replaced is True
    assert result.total_lots == 135  # fresh import, nothing left over to collide with

    (after,) = conn.execute("SELECT COUNT(*) FROM lots").fetchone()
    assert after == 135
    check_invariants(conn)
