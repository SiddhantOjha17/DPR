import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import operations
from app.operations import MoveError, UndoError
from app.routes.main_screen import fetch_grouped_positions
from app.web import current_user_id, get_conn, new_toast_id, parse_optional_int, require_permission, templates

router = APIRouter()


def _panel_context(
    request: Request,
    conn: sqlite3.Connection,
    lot_id: int,
    *,
    brand_id: int | None,
    error_message: str | None = None,
    toast_message: str | None = None,
    toast_undo_url: str | None = None,
    toast_undo_fields: dict | None = None,
) -> dict:
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
        "brand": brand_id,
        "error_message": error_message,
        "toast_message": toast_message,
        "toast_undo_url": toast_undo_url,
        "toast_undo_fields": toast_undo_fields or {},
        "toast_undo_htmx": True,
        "toast_id": new_toast_id(),
    }


def _table_context(conn: sqlite3.Connection, brand_id: int | None) -> dict:
    brands = conn.execute("SELECT id, name FROM brands WHERE active = 1 ORDER BY name").fetchall()
    data = fetch_grouped_positions(conn, brand_id)
    return {"brands": brands, "selected_brand": brand_id, "oob": True, **data}


def _render_panel(request, conn, lot_id, brand_id, **kwargs):
    context = _panel_context(request, conn, lot_id, brand_id=brand_id, **kwargs)
    return templates.TemplateResponse(request, "_side_panel.html", context)


def _render_panel_and_table(request, conn, lot_id, brand_id, **kwargs):
    context = {
        **_panel_context(request, conn, lot_id, brand_id=brand_id, **kwargs),
        **_table_context(conn, brand_id),
    }
    return templates.TemplateResponse(request, "_panel_and_table.html", context)


@router.get("/lots/{lot_id}/panel", response_class=HTMLResponse)
def get_panel(request: Request, lot_id: int, brand: str = "", conn=Depends(get_conn)):
    return _render_panel(request, conn, lot_id, parse_optional_int(brand))


@router.get("/lots/add-form", response_class=HTMLResponse)
def add_lot_form(request: Request, brand: str = "", conn=Depends(get_conn), _perm=Depends(require_permission("edit"))):
    brands = conn.execute("SELECT id, name FROM brands WHERE active = 1 ORDER BY name").fetchall()
    stages = conn.execute("SELECT id, name FROM stages WHERE active = 1 ORDER BY rank").fetchall()
    sub_brands = conn.execute(
        "SELECT sb.id, sb.name, b.name AS brand_name FROM sub_brands sb "
        "JOIN brands b ON b.id = sb.brand_id ORDER BY b.name, sb.name"
    ).fetchall()
    return templates.TemplateResponse(
        request,
        "_add_lot_form.html",
        {"request": request, "brands": brands, "stages": stages, "sub_brands": sub_brands, "brand": parse_optional_int(brand)},
    )


@router.post("/lots/add", response_class=HTMLResponse)
def add_lot(
    request: Request,
    conn=Depends(get_conn),
    brand_id: int = Form(...),
    ct_number: str = Form(...),
    total_qty: int = Form(...),
    starting_stage_id: int = Form(...),
    sub_brand_id: str = Form(""),
    material_code: str = Form(""),
    fabric: str = Form(""),
    fi_date: str = Form(""),
    fabric_date: str = Form(""),
    remark: str = Form(""),
    brand_filter: str = Form(""),
    _perm=Depends(require_permission("edit")),
):
    is_htmx = bool(request.headers.get("hx-request"))
    filter_brand_id = parse_optional_int(brand_filter)

    try:
        lot_id = operations.create_lot(
            conn,
            brand_id=brand_id,
            ct_number=ct_number,
            total_qty=total_qty,
            starting_stage_id=starting_stage_id,
            sub_brand_id=int(sub_brand_id) if sub_brand_id else None,
            material_code=material_code or None,
            fabric=fabric or None,
            fi_date=fi_date or None,
            fabric_date=fabric_date or None,
            remark=remark or None,
            moved_by=current_user_id(request),
        )
    except Exception as e:
        if is_htmx:
            brands = conn.execute("SELECT id, name FROM brands WHERE active = 1 ORDER BY name").fetchall()
            stages = conn.execute("SELECT id, name FROM stages WHERE active = 1 ORDER BY rank").fetchall()
            sub_brands = conn.execute(
                "SELECT sb.id, sb.name, b.name AS brand_name FROM sub_brands sb "
                "JOIN brands b ON b.id = sb.brand_id ORDER BY b.name, sb.name"
            ).fetchall()
            return templates.TemplateResponse(
                request,
                "_add_lot_form.html",
                {
                    "request": request, "brands": brands, "stages": stages, "sub_brands": sub_brands,
                    "brand": filter_brand_id, "error_message": f"Could not add lot: {e}",
                },
            )
        return RedirectResponse(url=f"/import?error=Could+not+add+lot:+{e}", status_code=303)

    opening_movement = conn.execute(
        "SELECT id FROM movements WHERE lot_id = ?", (lot_id,)
    ).fetchone()["id"]

    if not is_htmx:
        return RedirectResponse(
            url=f"/import?message=Added+lot+{ct_number}.&undo_url=/movements/{opening_movement}/undo&undo_lot_id={lot_id}",
            status_code=303,
        )

    return _render_panel_and_table(
        request, conn, lot_id, filter_brand_id,
        toast_message=f"Added lot {ct_number}.",
        toast_undo_url=f"/movements/{opening_movement}/undo",
        toast_undo_fields={"lot_id": lot_id, "brand": filter_brand_id or ""},
    )


@router.post("/lots/{lot_id}/move", response_class=HTMLResponse)
def move(
    request: Request,
    lot_id: int,
    from_stage_id: int = Form(...),
    to_stage_id: int = Form(...),
    qty: int = Form(...),
    note: str = Form(""),
    brand: str = Form(""),
    conn=Depends(get_conn),
    _perm=Depends(require_permission("move")),
):
    brand_id = parse_optional_int(brand)
    try:
        movement_id = operations.move_pieces(
            conn,
            lot_id=lot_id,
            from_stage_id=from_stage_id,
            to_stage_id=to_stage_id,
            qty=qty,
            moved_by=current_user_id(request),
            note=note or None,
        )
    except MoveError as e:
        return _render_panel(request, conn, lot_id, brand_id, error_message=str(e))
    return _render_panel_and_table(
        request, conn, lot_id, brand_id,
        toast_message="Moved.",
        toast_undo_url=f"/movements/{movement_id}/undo",
        toast_undo_fields={"lot_id": lot_id, "brand": brand_id or ""},
    )


@router.post("/lots/{lot_id}/edit", response_class=HTMLResponse)
def edit(
    request: Request,
    lot_id: int,
    conn=Depends(get_conn),
    sub_brand_id: str = Form(""),
    remark: str = Form(""),
    material_code: str = Form(""),
    fabric: str = Form(""),
    fi_date: str = Form(""),
    fabric_date: str = Form(""),
    total_qty: str = Form(""),
    ct_number: str = Form(""),
    acr: str = Form(""),
    brand: str = Form(""),
    _perm=Depends(require_permission("edit")),
):
    brand_id = parse_optional_int(brand)
    before = conn.execute("SELECT * FROM lots WHERE id = ?", (lot_id,)).fetchone()

    try:
        operations.update_lot_details(
            conn,
            lot_id=lot_id,
            sub_brand_id=int(sub_brand_id) if sub_brand_id else None,
            remark=remark or None,
            material_code=material_code or None,
            fabric=fabric or None,
            fi_date=fi_date or None,
            fabric_date=fabric_date or None,
            total_qty=int(total_qty) if total_qty else None,
            ct_number=ct_number or None,
            acr=int(acr) if acr else None,
        )
    except MoveError as e:
        return _render_panel(request, conn, lot_id, brand_id, error_message=str(e))

    return _render_panel_and_table(
        request, conn, lot_id, brand_id,
        toast_message="Saved.",
        toast_undo_url=f"/lots/{lot_id}/edit",
        toast_undo_fields={
            "brand": brand_id or "",
            "sub_brand_id": before["sub_brand_id"] or "",
            "remark": before["remark"] or "",
            "material_code": before["material_code"] or "",
            "fabric": before["fabric"] or "",
            "fi_date": (before["fi_date"] or "")[:10],
            "fabric_date": (before["fabric_date"] or "")[:10],
            "total_qty": before["total_qty"],
            "ct_number": before["ct_number"] or "",
            "acr": before["acr"] if before["acr"] is not None else "",
        },
    )


@router.post("/movements/{movement_id}/undo", response_class=HTMLResponse)
def undo(
    request: Request,
    movement_id: int,
    lot_id: int = Form(...),
    brand: str = Form(""),
    conn=Depends(get_conn),
    _perm=Depends(require_permission("move")),
):
    brand_id = parse_optional_int(brand)
    is_htmx = bool(request.headers.get("hx-request"))

    try:
        new_movement_id = operations.undo_movement(conn, movement_id=movement_id, moved_by=current_user_id(request))
    except UndoError as e:
        if not is_htmx:
            return RedirectResponse(url=f"{request.headers.get('referer', '/')}", status_code=303)
        return _render_panel(request, conn, lot_id, brand_id, error_message=str(e))

    if not is_htmx:
        # Only non-htmx caller today is the Import page's single-lot-add toast.
        return RedirectResponse(url="/import?message=Removed.", status_code=303)

    if new_movement_id is None:
        # The lot's sole (opening) movement was undone - the lot itself is gone.
        response = templates.TemplateResponse(request, "_table.html", _table_context(conn, brand_id))
        return HTMLResponse(
            "<div class='success-banner'>Lot removed.</div>" + response.body.decode()
        )

    return _render_panel_and_table(
        request, conn, lot_id, brand_id,
        toast_message="Undone.",
        toast_undo_url=f"/movements/{new_movement_id}/undo",
        toast_undo_fields={"lot_id": lot_id, "brand": brand_id or ""},
    )


@router.post("/lots/{lot_id}/ship", response_class=HTMLResponse)
def ship(
    request: Request,
    lot_id: int,
    brand: str = Form(""),
    conn=Depends(get_conn),
    _perm=Depends(require_permission("ship")),
):
    brand_id = parse_optional_int(brand)
    try:
        operations.mark_shipped(conn, lot_id=lot_id)
    except MoveError as e:
        return _render_panel(request, conn, lot_id, brand_id, error_message=str(e))

    table_response = templates.TemplateResponse(request, "_table.html", _table_context(conn, brand_id))
    panel_html = (
        "<div class='success-banner' id='toast-ship'>Shipped. Lot moved to archive."
        f"<form class=\"inline\" hx-post=\"/lots/{lot_id}/reopen\" hx-target=\"#side-panel\" hx-swap=\"innerHTML\">"
        f"<input type=\"hidden\" name=\"brand\" value=\"{brand_id or ''}\">"
        "<button type=\"submit\">Undo</button></form>"
        "</div>"
        "<script>setTimeout(function(){var t=document.getElementById('toast-ship');"
        "if(t&&t.parentNode)t.parentNode.removeChild(t);},6000);</script>"
    )
    return HTMLResponse(panel_html + table_response.body.decode())


@router.post("/lots/{lot_id}/reopen", response_class=HTMLResponse)
def reopen(
    request: Request,
    lot_id: int,
    brand: str = Form(""),
    conn=Depends(get_conn),
    _perm=Depends(require_permission("ship")),
):
    brand_id = parse_optional_int(brand)
    is_htmx = bool(request.headers.get("hx-request"))
    try:
        operations.reopen_lot(conn, lot_id=lot_id)
    except MoveError as e:
        if is_htmx:
            return _render_panel(request, conn, lot_id, brand_id, error_message=str(e))
        return RedirectResponse(url=f"/archive?message=Could+not+undo:+{e}", status_code=303)

    if not is_htmx:
        return RedirectResponse(url="/archive?message=Lot+reopened+to+FI+Done.", status_code=303)

    return _render_panel_and_table(request, conn, lot_id, brand_id, toast_message="Reopened to FI Done.")
