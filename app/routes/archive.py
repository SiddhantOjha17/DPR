from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.web import base_context, get_conn, parse_optional_int, templates

router = APIRouter()


def _valid_date(value: str) -> str:
    """Return value if it parses as an ISO date, else '' - so a malformed date
    input is silently ignored as "no filter" rather than raising."""
    if not value:
        return ""
    try:
        date.fromisoformat(value)
        return value
    except ValueError:
        return ""


@router.get("/archive", response_class=HTMLResponse)
def archive(
    request: Request,
    ct: str = "",
    brand: str = "",
    code: str = "",
    date_from: str = "",
    date_to: str = "",
    message: str = "",
    conn=Depends(get_conn),
):
    brand_id = parse_optional_int(brand)
    date_from = _valid_date(date_from)
    date_to = _valid_date(date_to)

    query = (
        "SELECT l.id, l.ct_number, l.material_code, l.fabric, l.total_qty, "
        "l.closed_at, b.name AS brand_name "
        "FROM lots l JOIN brands b ON b.id = l.brand_id "
        "WHERE l.closed_at IS NOT NULL"
    )
    params: list = []
    if ct.strip():
        query += " AND l.ct_number LIKE ?"
        params.append(f"%{ct.strip()}%")
    if brand_id:
        query += " AND b.id = ?"
        params.append(brand_id)
    if code.strip():
        query += " AND l.material_code LIKE ?"
        params.append(f"%{code.strip()}%")
    if date_from:
        query += " AND l.closed_at >= ?"
        params.append(date_from)
    if date_to:
        query += " AND l.closed_at <= ?"
        params.append(date_to + "T23:59:59")
    query += " ORDER BY l.closed_at DESC"

    lots = conn.execute(query, params).fetchall()
    brands = conn.execute("SELECT id, name FROM brands ORDER BY name").fetchall()

    return templates.TemplateResponse(
        request,
        "archive.html",
        {
            **base_context(request, conn),
            "lots": lots,
            "brands": brands,
            "filters": {"ct": ct, "brand": brand_id, "code": code, "date_from": date_from, "date_to": date_to},
            "message": message,
        },
    )
