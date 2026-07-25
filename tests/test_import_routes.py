"""HTTP-level regression test: the /import route's `mode` form field must
actually reach import_workbook(). A prior bug declared `mode: str = "add"`
without `Form(...)`, so FastAPI treated it as a query param and silently
ignored the multipart `mode=replace` field, always defaulting to "add" -
caught only by driving the real route, not by testing import_workbook()
directly."""

from pathlib import Path

from app import db

FIXTURE = Path(__file__).parent / "fixtures" / "all_brand_dpr.xlsx"


def _upload(client, mode):
    with FIXTURE.open("rb") as f:
        return client.post(
            "/import",
            files={"file": ("all_brand_dpr.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"mode": mode},
        )


def test_import_route_add_mode_skips_duplicates(client):
    first = _upload(client, "add")
    assert first.status_code == 200
    conn = db.get_connection()
    (count,) = conn.execute("SELECT COUNT(*) FROM lots").fetchone()
    conn.close()
    assert count == 330

    second = _upload(client, "add")
    assert second.status_code == 200
    assert "already exists" in second.text


def test_import_route_replace_mode_actually_wipes_first(client):
    _upload(client, "add")
    conn = db.get_connection()
    (before,) = conn.execute("SELECT COUNT(*) FROM lots").fetchone()
    conn.close()
    assert before == 330

    resp = _upload(client, "replace")
    assert resp.status_code == 200
    assert "Replaced existing data" in resp.text
    assert "Imported 330 lots" in resp.text

    conn = db.get_connection()
    (after,) = conn.execute("SELECT COUNT(*) FROM lots").fetchone()
    conn.close()
    assert after == 330  # not 330+330 - proves the wipe actually happened
