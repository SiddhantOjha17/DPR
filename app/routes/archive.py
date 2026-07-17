from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.web import base_context, get_conn, templates

router = APIRouter()


@router.get("/archive", response_class=HTMLResponse)
def archive(
    request: Request,
    ct: str = "",
    brand: int | None = None,
    code: str = "",
    date_from: str = "",
    date_to: str = "",
    conn=Depends(get_conn),
):
    query = (
        "SELECT l.id, l.ct_number, l.material_code, l.fabric, l.total_qty, "
        "l.closed_at, b.name AS brand_name "
        "FROM lots l JOIN brands b ON b.id = l.brand_id "
        "WHERE l.closed_at IS NOT NULL"
    )
    params: list = []
    if ct:
        query += " AND l.ct_number LIKE ?"
        params.append(f"%{ct}%")
    if brand:
        query += " AND b.id = ?"
        params.append(brand)
    if code:
        query += " AND l.material_code LIKE ?"
        params.append(f"%{code}%")
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
            "filters": {"ct": ct, "brand": brand, "code": code, "date_from": date_from, "date_to": date_to},
        },
    )
