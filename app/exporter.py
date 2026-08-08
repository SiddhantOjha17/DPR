import io
from datetime import datetime, timezone

from openpyxl import Workbook


def export_workbook(conn) -> io.BytesIO:
    wb = Workbook()
    detail = wb.active
    detail.title = "DPR"
    detail.append(
        [
            "Brand", "Sub-brand", "CT", "Code", "Fabric", "Order Qty", "ACR",
            "Remark", "FI Date", "Fab Date", "Current Stage", "Days",
        ]
    )

    rows = conn.execute(
        "SELECT l.id AS lot_id, p.qty AS stage_qty, p.entered_at, s.name AS stage_name, s.rank AS stage_rank, "
        "l.ct_number, l.material_code, l.fabric, l.total_qty, l.acr, l.remark, "
        "l.fi_date, l.fabric_date, b.name AS brand_name, sb.name AS sub_brand_name "
        "FROM positions p "
        "JOIN lots l ON l.id = p.lot_id "
        "JOIN stages s ON s.id = p.stage_id "
        "JOIN brands b ON b.id = l.brand_id "
        "LEFT JOIN sub_brands sb ON sb.id = l.sub_brand_id "
        "WHERE l.closed_at IS NULL "
        "ORDER BY s.rank, b.name, l.ct_number"
    ).fetchall()

    now = datetime.now(timezone.utc)
    current_stage = None
    subtotal = 0
    acr_subtotal = 0
    grand_total = 0
    acr_grand_total = 0
    seen_lot_ids: set[int] = set()
    stage_summary: dict[str, dict[str, int]] = {}

    def flush_subtotal():
        if current_stage is not None:
            detail.append(["", "", "", "", "Subtotal", subtotal, acr_subtotal, "", "", "", "", ""])

    for row in rows:
        if row["stage_name"] != current_stage:
            flush_subtotal()
            current_stage = row["stage_name"]
            subtotal = 0
            acr_subtotal = 0
            detail.append([current_stage])

        days = (now - datetime.fromisoformat(row["entered_at"])).days
        detail.append(
            [
                row["brand_name"],
                row["sub_brand_name"] or "",
                row["ct_number"],
                row["material_code"] or "",
                row["fabric"] or "",
                row["stage_qty"],
                row["acr"] if row["acr"] is not None else "",
                row["remark"] or "",
                row["fi_date"] or "",
                row["fabric_date"] or "",
                row["stage_name"],
                days,
            ]
        )
        subtotal += row["stage_qty"]
        acr_subtotal += row["acr"] or 0
        grand_total += row["stage_qty"]

        summary = stage_summary.setdefault(row["stage_name"], {"lots": 0, "qty": 0, "acr": 0})
        summary["lots"] += 1
        summary["qty"] += row["stage_qty"]
        summary["acr"] += row["acr"] or 0

        # ACR is a flat per-lot value, not split-aware like stage_qty - dedupe by
        # lot so a split lot's ACR is only counted once in the true grand total
        # (per-stage subtotals above stay naive; see main_screen.py's identical
        # comment for the full reasoning).
        if row["lot_id"] not in seen_lot_ids:
            seen_lot_ids.add(row["lot_id"])
            acr_grand_total += row["acr"] or 0

    flush_subtotal()
    detail.append(["", "", "", "", "Grand total", grand_total, acr_grand_total, "", "", "", "", ""])

    report = wb.create_sheet("Report")
    report.append(["Stage", "Lots", "Order Qty", "ACR"])
    for stage_name, summary in stage_summary.items():
        report.append([stage_name, summary["lots"], summary["qty"], summary["acr"]])
    report.append(
        ["Grand total", sum(s["lots"] for s in stage_summary.values()), grand_total, acr_grand_total]
    )

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer
