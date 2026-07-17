import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import HTMLResponse

from app.importer import ImportReconciliationError, import_workbook
from app.web import base_context, get_conn, templates

router = APIRouter()


@router.get("/import", response_class=HTMLResponse)
def import_form(request: Request, conn=Depends(get_conn)):
    return templates.TemplateResponse(request, "import.html", {**base_context(request, conn)})


@router.post("/import", response_class=HTMLResponse)
def do_import(request: Request, file: UploadFile, conn=Depends(get_conn)):
    (existing_lots,) = conn.execute("SELECT COUNT(*) FROM lots").fetchone()
    if existing_lots > 0:
        return templates.TemplateResponse(
            request,
            "import.html",
            {
                **base_context(request, conn),
                "error": "The database already has lots in it. Import is only for first-run setup.",
            },
        )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / file.filename
        with tmp_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        try:
            result = import_workbook(str(tmp_path), conn)
        except ImportReconciliationError as e:
            return templates.TemplateResponse(
                request, "import.html", {**base_context(request, conn), "error": str(e)}
            )

    return templates.TemplateResponse(
        request, "import.html", {**base_context(request, conn), "result": result}
    )
