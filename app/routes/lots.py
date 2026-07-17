import sqlite3

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse

from app import operations
from app.operations import MoveError, UndoError
from app.web import current_user_id, get_conn, templates

router = APIRouter()


def _panel_context(request: Request, conn: sqlite3.Connection, lot_id: int, message: str | None = None, message_class: str = "error-banner") -> dict:
    lot = conn.execute(
        "SELECT l.*, b.name AS brand_name FROM lots l JOIN brands b ON b.id = l.brand_id WHERE l.id = ?",
        (lot_id,),
    ).fetchone()

    positions = conn.execute(
        "SELECT p.stage_id, p.qty, p.entered_at, s.name AS stage_name "
        "FROM positions p JOIN stages s ON s.id = p.stage_id "
        "WHERE p.lot_id = ? ORDER BY s.rank",
        (lot_id,),
    ).fetchall()
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    position_rows = [
        {
            "stage_id": p["stage_id"],
            "stage_name": p["stage_name"],
            "qty": p["qty"],
            "days": (now - datetime.fromisoformat(p["entered_at"])).days,
        }
        for p in positions
    ]

    stages = conn.execute("SELECT id, name FROM stages WHERE active = 1 ORDER BY rank").fetchall()
    sub_brands = conn.execute(
        "SELECT id, name FROM sub_brands WHERE brand_id = ? ORDER BY name", (lot["brand_id"],)
    ).fetchall()

    fi_done = conn.execute("SELECT id FROM stages WHERE name = 'FI Done'").fetchone()["id"]
    can_ship = bool(positions) and all(p["stage_id"] == fi_done for p in positions)

    timeline = operations.days_in_stage_historical(conn, lot_id)

    movements = conn.execute(
        "SELECT m.id, m.moved_at, m.qty, m.note, m.reverses_id, "
        "fs.name AS from_stage_name, ts.name AS to_stage_name, u.name AS moved_by_name "
        "FROM movements m "
        "LEFT JOIN stages fs ON fs.id = m.from_stage_id "
        "JOIN stages ts ON ts.id = m.to_stage_id "
        "LEFT JOIN users u ON u.id = m.moved_by "
        "WHERE m.lot_id = ? ORDER BY m.moved_at DESC, m.id DESC",
        (lot_id,),
    ).fetchall()
    reversed_ids = {
        row["reverses_id"] for row in movements if row["reverses_id"] is not None
    }
    history = [
        {**dict(m), "is_reversed": m["id"] in reversed_ids} for m in movements
    ]

    return {
        "request": request,
        "lot": lot,
        "positions": position_rows,
        "stages": stages,
        "sub_brands": sub_brands,
        "can_ship": can_ship,
        "timeline": timeline,
        "history": history,
        "message": message,
        "message_class": message_class,
    }


def _render_panel(request, conn, lot_id, message=None, message_class="error-banner", trigger_refresh=False):
    context = _panel_context(request, conn, lot_id, message, message_class)
    response = templates.TemplateResponse(request, "_side_panel.html", context)
    if trigger_refresh:
        response.headers["HX-Trigger"] = "dpr:refresh"
    return response


@router.get("/lots/{lot_id}/panel", response_class=HTMLResponse)
def get_panel(request: Request, lot_id: int, conn=Depends(get_conn)):
    return _render_panel(request, conn, lot_id)


@router.post("/lots/{lot_id}/move", response_class=HTMLResponse)
def move(
    request: Request,
    lot_id: int,
    from_stage_id: int = Form(...),
    to_stage_id: int = Form(...),
    qty: int = Form(...),
    note: str = Form(""),
    conn=Depends(get_conn),
):
    try:
        operations.move_pieces(
            conn,
            lot_id=lot_id,
            from_stage_id=from_stage_id,
            to_stage_id=to_stage_id,
            qty=qty,
            moved_by=current_user_id(request),
            note=note or None,
        )
    except MoveError as e:
        return _render_panel(request, conn, lot_id, message=str(e))
    return _render_panel(request, conn, lot_id, message="Moved.", message_class="success-banner", trigger_refresh=True)


@router.post("/lots/{lot_id}/edit", response_class=HTMLResponse)
def edit(
    request: Request,
    lot_id: int,
    conn=Depends(get_conn),
    sub_brand_id: str = Form(""),
    remark: str = Form(""),
    material_code: str = Form(""),
    fabric: str = Form(""),
    wash: str = Form(""),
    fi_date: str = Form(""),
    fabric_date: str = Form(""),
):
    operations.update_lot_details(
        conn,
        lot_id=lot_id,
        sub_brand_id=int(sub_brand_id) if sub_brand_id else None,
        remark=remark or None,
        material_code=material_code or None,
        fabric=fabric or None,
        wash=wash or None,
        fi_date=fi_date or None,
        fabric_date=fabric_date or None,
    )
    return _render_panel(request, conn, lot_id, message="Saved.", message_class="success-banner", trigger_refresh=True)


@router.post("/movements/{movement_id}/undo", response_class=HTMLResponse)
def undo(request: Request, movement_id: int, lot_id: int = Form(...), conn=Depends(get_conn)):
    try:
        operations.undo_movement(conn, movement_id=movement_id, moved_by=current_user_id(request))
    except UndoError as e:
        return _render_panel(request, conn, lot_id, message=str(e))
    return _render_panel(request, conn, lot_id, message="Undone.", message_class="success-banner", trigger_refresh=True)


@router.post("/lots/{lot_id}/ship", response_class=HTMLResponse)
def ship(request: Request, lot_id: int, conn=Depends(get_conn)):
    try:
        operations.mark_shipped(conn, lot_id=lot_id)
    except MoveError as e:
        return _render_panel(request, conn, lot_id, message=str(e))
    response = HTMLResponse(
        "<div id='side-panel'><div class='success-banner'>Shipped. Lot moved to archive.</div></div>"
    )
    response.headers["HX-Trigger"] = "dpr:refresh"
    return response
