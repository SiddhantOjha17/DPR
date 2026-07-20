from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.exporter import export_workbook
from app.web import get_conn, require_permission

router = APIRouter()


@router.get("/export")
def export(conn=Depends(get_conn), _perm=Depends(require_permission("admin"))):
    buffer = export_workbook(conn)
    filename = f"DPR-{date.today().isoformat()}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
