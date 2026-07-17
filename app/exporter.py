import io
from datetime import datetime, timezone

from openpyxl import Workbook


def export_workbook(conn) -> io.BytesIO:
    wb = Workbook()
    detail = wb.active
    detail.title = "DPR"
    detail.append(
        [
            "Brand", "Sub-brand", "CT", "Code", "Fabric", "Wash", "Qty",
            "Remark", "FI Date", "Fab Date", "Current Stage", "Days",
        ]
    )

    rows = conn.execute(
        "SELECT p.qty AS stage_qty, p.entered_at, s.name AS stage_name, s.rank AS stage_rank, "
        "l.ct_number, l.material_code, l.fabric, l.wash, l.total_qty, l.remark, "
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
    grand_total = 0
    stage_summary: dict[str, dict[str, int]] = {}

    def flush_subtotal():
        if current_stage is not None:
            detail.append(["", "", "", "", "", "Subtotal", subtotal, "", "", "", "", ""])

    for row in rows:
        if row["stage_name"] != current_stage:
            flush_subtotal()
            current_stage = row["stage_name"]
            subtotal = 0
            detail.append([current_stage])

        days = (now - datetime.fromisoformat(row["entered_at"])).days
        detail.append(
            [
                row["brand_name"],
                row["sub_brand_name"] or "",
                row["ct_number"],
                row["material_code"] or "",
                row["fabric"] or "",
                row["wash"] or "",
                row["stage_qty"],
                row["remark"] or "",
                row["fi_date"] or "",
                row["fabric_date"] or "",
                row["stage_name"],
                days,
            ]
        )
        subtotal += row["stage_qty"]
        grand_total += row["stage_qty"]

        summary = stage_summary.setdefault(row["stage_name"], {"lots": 0, "qty": 0})
        summary["lots"] += 1
        summary["qty"] += row["stage_qty"]

    flush_subtotal()
    detail.append(["", "", "", "", "", "Grand total", grand_total, "", "", "", "", ""])

    report = wb.create_sheet("Report")
    report.append(["Stage", "Lots", "Qty"])
    for stage_name, summary in stage_summary.items():
        report.append([stage_name, summary["lots"], summary["qty"]])
    report.append(["Grand total", sum(s["lots"] for s in stage_summary.values()), grand_total])

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer
