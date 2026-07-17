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
