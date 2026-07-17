import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.web import base_context, get_conn, templates

router = APIRouter()


def fetch_grouped_positions(conn: sqlite3.Connection, brand_id: int | None) -> dict:
    split_lot_ids = {
        row["lot_id"]
        for row in conn.execute(
            "SELECT lot_id FROM positions GROUP BY lot_id HAVING COUNT(*) > 1"
        )
    }

    query = (
        "SELECT p.lot_id, p.stage_id, p.qty AS stage_qty, p.entered_at, "
        "s.name AS stage_name, s.rank AS stage_rank, "
        "l.ct_number, l.material_code, l.fabric, l.wash, l.total_qty, l.remark, "
        "l.fi_date, l.fabric_date, b.name AS brand_name, sb.name AS sub_brand_name "
        "FROM positions p "
        "JOIN lots l ON l.id = p.lot_id "
        "JOIN stages s ON s.id = p.stage_id "
        "JOIN brands b ON b.id = l.brand_id "
        "LEFT JOIN sub_brands sb ON sb.id = l.sub_brand_id "
        "WHERE l.closed_at IS NULL"
    )
    params: list = []
    if brand_id is not None:
        query += " AND b.id = ?"
        params.append(brand_id)
    query += " ORDER BY s.rank, b.name, l.ct_number"

    now = datetime.now(timezone.utc)
    groups: dict[int, dict] = {}
    grand_total = 0
    for row in conn.execute(query, params):
        entered = datetime.fromisoformat(row["entered_at"])
        days = (now - entered).days
        stage_id = row["stage_id"]
        group = groups.setdefault(
            stage_id,
            {"stage_name": row["stage_name"], "stage_rank": row["stage_rank"], "rows": [], "subtotal": 0},
        )
        group["rows"].append(
            {
                "lot_id": row["lot_id"],
                "brand_name": row["brand_name"],
                "sub_brand_name": row["sub_brand_name"],
                "ct_number": row["ct_number"],
                "material_code": row["material_code"],
                "fabric": row["fabric"],
                "wash": row["wash"],
                "remark": row["remark"],
                "fi_date": row["fi_date"],
                "fabric_date": row["fabric_date"],
                "stage_name": row["stage_name"],
                "stage_qty": row["stage_qty"],
                "total_qty": row["total_qty"],
                "is_split": row["lot_id"] in split_lot_ids,
                "days": days,
            }
        )
        group["subtotal"] += row["stage_qty"]
        grand_total += row["stage_qty"]

    ordered_groups = [groups[k] for k in sorted(groups, key=lambda k: groups[k]["stage_rank"])]
    return {"groups": ordered_groups, "grand_total": grand_total}


@router.get("/", response_class=HTMLResponse)
def main_screen(request: Request, brand: int | None = None, conn=Depends(get_conn)):
    brands = conn.execute("SELECT id, name FROM brands WHERE active = 1 ORDER BY name").fetchall()
    data = fetch_grouped_positions(conn, brand)
    context = {
        **base_context(request, conn),
        "brands": brands,
        "selected_brand": brand,
        **data,
    }
    if request.headers.get("hx-request"):
        return templates.TemplateResponse(request, "_table.html", context)
    return templates.TemplateResponse(request, "main_screen.html", context)
