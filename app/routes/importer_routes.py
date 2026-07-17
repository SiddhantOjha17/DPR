import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse

from app.importer import import_workbook
from app.web import base_context, get_conn, new_toast_id, templates

router = APIRouter()


def _lot_form_options(conn):
    return {
        "brands": conn.execute("SELECT id, name FROM brands WHERE active = 1 ORDER BY name").fetchall(),
        "stages": conn.execute("SELECT id, name FROM stages WHERE active = 1 ORDER BY rank").fetchall(),
        "sub_brands": conn.execute(
            "SELECT sb.id, sb.name, b.name AS brand_name FROM sub_brands sb "
            "JOIN brands b ON b.id = sb.brand_id ORDER BY b.name, sb.name"
        ).fetchall(),
    }


@router.get("/import", response_class=HTMLResponse)
def import_form(
    request: Request,
    message: str = "",
    error: str = "",
    undo_url: str = "",
    undo_lot_id: str = "",
    conn=Depends(get_conn),
):
    (existing_lot_count,) = conn.execute("SELECT COUNT(*) FROM lots").fetchone()
    return templates.TemplateResponse(
        request,
        "import.html",
        {
            **base_context(request, conn),
            **_lot_form_options(conn),
            "existing_lot_count": existing_lot_count,
            "error": error,
            "toast_message": message,
            "toast_undo_url": undo_url,
            "toast_undo_fields": {"lot_id": undo_lot_id} if undo_url else {},
            "toast_undo_htmx": False,
            "toast_id": new_toast_id(),
        },
    )


@router.post("/import", response_class=HTMLResponse)
def do_import(request: Request, file: UploadFile, mode: str = Form("add"), conn=Depends(get_conn)):
    result = None
    error = ""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / file.filename
        with tmp_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        try:
            result = import_workbook(str(tmp_path), conn, wipe_existing=(mode == "replace"))
        except Exception as e:
            error = f"Import failed: {e}"

    (existing_lot_count,) = conn.execute("SELECT COUNT(*) FROM lots").fetchone()
    return templates.TemplateResponse(
        request,
        "import.html",
        {
            **base_context(request, conn),
            **_lot_form_options(conn),
            "existing_lot_count": existing_lot_count,
            "error": error,
            "result": result,
        },
    )
