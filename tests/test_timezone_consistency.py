"""Regression test: every stored timestamp must be timezone-aware (UTC), so that
`operations.days_in_stage_current` / `_historical` and the main-screen "Days" column
can safely subtract `datetime.now(timezone.utc)` from any `entered_at`/`moved_at`
value without raising `TypeError: can't subtract offset-naive and offset-aware
datetimes`. The importer previously used a naive `datetime.now()` for its seed
timestamp and only broke on the actual main screen route, not in unit tests that
called `import_workbook` directly - this test exercises the same downstream code
path the route exercises."""

from pathlib import Path

from app import operations
from app.importer import import_workbook
from app.routes.main_screen import fetch_grouped_positions

FIXTURE = Path(__file__).parent / "fixtures" / "june_dpr.xlsx"


def test_days_in_stage_current_after_import_does_not_raise(conn):
    import_workbook(str(FIXTURE), conn)
    lot_id = conn.execute("SELECT id FROM lots LIMIT 1").fetchone()["id"]
    result = operations.days_in_stage_current(conn, lot_id)
    assert result[0]["days"] >= 0


def test_days_in_stage_historical_after_import_does_not_raise(conn):
    import_workbook(str(FIXTURE), conn)
    lot_id = conn.execute("SELECT id FROM lots LIMIT 1").fetchone()["id"]
    result = operations.days_in_stage_historical(conn, lot_id)
    assert result[0]["total_days"] >= 0


def test_main_screen_grouping_after_import_does_not_raise(conn):
    import_workbook(str(FIXTURE), conn)
    data = fetch_grouped_positions(conn, brand_id=None)
    assert data["grand_total"] == 90908
    assert sum(len(g["rows"]) for g in data["groups"]) == 135
