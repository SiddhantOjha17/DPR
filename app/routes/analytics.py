from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app import analytics
from app.web import base_context, get_conn, templates

router = APIRouter()


@router.get("/analytics", response_class=HTMLResponse)
def analytics_screen(request: Request, conn=Depends(get_conn)):
    return templates.TemplateResponse(
        request,
        "analytics.html",
        {
            **base_context(request, conn),
            "longest_in_stage": analytics.longest_time_in_stage(conn),
            "fi_risk": analytics.fi_date_risk(conn),
            "avg_days": analytics.avg_days_per_stage(conn),
            "avg_days_per_brand": analytics.avg_days_per_stage_per_brand(conn),
            "throughput": analytics.throughput(conn),
            "wip_over_time": analytics.wip_over_time(conn),
        },
    )
