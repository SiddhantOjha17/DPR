from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app import analytics, charts
from app.web import base_context, get_conn, parse_optional_int, templates

router = APIRouter()

TREND_WEEKS = 8


def _cutoff_week(now: datetime) -> str:
    cutoff = now - timedelta(weeks=TREND_WEEKS)
    year, week, _ = cutoff.isocalendar()
    return f"{year}-W{week:02d}"


@router.get("/analytics", response_class=HTMLResponse)
def analytics_screen(request: Request, brand: str = "", conn=Depends(get_conn)):
    brand_id = parse_optional_int(brand)
    brands = conn.execute("SELECT id, name FROM brands WHERE active = 1 ORDER BY name").fetchall()
    stage_order = [
        r["name"] for r in conn.execute("SELECT name FROM stages WHERE active = 1 ORDER BY rank")
    ]

    now = datetime.now(timezone.utc)
    cutoff_date = (now - timedelta(weeks=TREND_WEEKS)).strftime("%Y-%m-%d")
    cutoff_week = _cutoff_week(now)

    kpis = analytics.summary_kpis(conn, brand_id)
    longest_in_stage = analytics.longest_time_in_stage(conn, brand_id)
    fi_risk = analytics.fi_date_risk(conn, brand_id)
    avg_days = analytics.avg_days_per_stage(conn, brand_id)

    throughput_full = analytics.throughput(conn, brand_id)
    throughput_windowed = [r for r in throughput_full if r["week"] >= cutoff_week]

    wip_full = analytics.wip_over_time(conn, brand_id)
    wip_windowed = [s for s in wip_full if s["date"] >= cutoff_date]

    # --- Charts ---
    avg_days_sorted = sorted(avg_days.items(), key=lambda kv: kv[1], reverse=True)
    avg_days_chart = charts.bar_chart_horizontal(avg_days_sorted, unit=" d")

    throughput_chart = charts.bar_chart_vertical(
        [(r["week"].split("-W")[1], r["qty"]) for r in throughput_windowed]
    )

    wip_dates = [s["date"] for s in wip_windowed]
    wip_by_date = {s["date"]: s["by_stage"] for s in wip_windowed}
    wip_chart = charts.stacked_bar_chart_vertical(wip_dates, stage_order, wip_by_date)

    # --- Per-brand heatmap (only meaningful for "all brands") ---
    heatmap = None
    if brand_id is None:
        avg_days_per_brand = analytics.avg_days_per_stage_per_brand(conn)
        all_values = [v for stages in avg_days_per_brand.values() for v in stages.values()]
        min_v, max_v = (min(all_values), max(all_values)) if all_values else (0, 1)
        heatmap_rows = []
        for brand_name, stage_values in avg_days_per_brand.items():
            if not stage_values:
                continue
            cells = []
            for stage_name in stage_order:
                value = stage_values.get(stage_name)
                if value is None:
                    cells.append({"value": None, "bg": None, "fg": None})
                else:
                    bg = charts.heatmap_color(value, min_v, max_v)
                    cells.append({"value": value, "bg": bg, "fg": charts.heatmap_text_color(bg)})
            heatmap_rows.append({"brand_name": brand_name, "cells": cells})
        heatmap = {"stage_order": stage_order, "rows": heatmap_rows}

    return templates.TemplateResponse(
        request,
        "analytics.html",
        {
            **base_context(request, conn),
            "brands": brands,
            "selected_brand": brand_id,
            "kpis": kpis,
            "longest_in_stage": longest_in_stage,
            "fi_risk": fi_risk,
            "avg_days_chart": avg_days_chart,
            "throughput_chart": throughput_chart,
            "throughput": throughput_windowed,
            "wip_chart": wip_chart,
            "wip_over_time": wip_windowed,
            "stage_order": stage_order,
            "heatmap": heatmap,
            "trend_weeks": TREND_WEEKS,
        },
    )
