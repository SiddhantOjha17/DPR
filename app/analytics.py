import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from app import operations


def longest_time_in_stage(conn: sqlite3.Connection, brand_id: int | None = None) -> list[dict]:
    query = (
        "SELECT p.lot_id, p.stage_id, p.qty, p.entered_at, s.name AS stage_name, "
        "l.ct_number, b.name AS brand_name "
        "FROM positions p "
        "JOIN lots l ON l.id = p.lot_id "
        "JOIN stages s ON s.id = p.stage_id "
        "JOIN brands b ON b.id = l.brand_id "
        "WHERE l.closed_at IS NULL"
    )
    params: list = []
    if brand_id is not None:
        query += " AND b.id = ?"
        params.append(brand_id)
    query += " ORDER BY p.entered_at ASC"

    rows = conn.execute(query, params).fetchall()
    now = datetime.now(timezone.utc)
    result = [
        {
            "lot_id": r["lot_id"],
            "ct_number": r["ct_number"],
            "brand_name": r["brand_name"],
            "stage_name": r["stage_name"],
            "qty": r["qty"],
            "days": (now - datetime.fromisoformat(r["entered_at"])).days,
        }
        for r in rows
    ]
    result.sort(key=lambda r: r["days"], reverse=True)
    return result


def avg_days_per_stage(conn: sqlite3.Connection, brand_id: int | None = None) -> dict[str, float]:
    return _avg_days_per_stage(conn, brand_id=brand_id)


def avg_days_per_stage_per_brand(conn: sqlite3.Connection) -> dict[str, dict[str, float]]:
    brands = conn.execute("SELECT id, name FROM brands ORDER BY name").fetchall()
    return {b["name"]: _avg_days_per_stage(conn, brand_id=b["id"]) for b in brands}


def _avg_days_per_stage(conn: sqlite3.Connection, brand_id: int | None) -> dict[str, float]:
    query = "SELECT id FROM lots"
    params: list = []
    if brand_id is not None:
        query += " WHERE brand_id = ?"
        params.append(brand_id)
    lot_ids = [r["id"] for r in conn.execute(query, params)]

    totals: dict[str, list[int]] = defaultdict(list)
    for lot_id in lot_ids:
        for entry in operations.days_in_stage_historical(conn, lot_id):
            if entry["last_left"] is not None:
                totals[entry["stage_name"]].append(entry["total_days"])

    return {
        stage: round(sum(days) / len(days), 1)
        for stage, days in totals.items()
        if days
    }


def throughput(conn: sqlite3.Connection, brand_id: int | None = None) -> list[dict]:
    fi_done = conn.execute("SELECT id FROM stages WHERE name = 'FI Done'").fetchone()["id"]
    query = (
        "SELECT m.moved_at, m.qty FROM movements m JOIN lots l ON l.id = m.lot_id "
        "WHERE m.to_stage_id = ? AND m.from_stage_id IS NOT NULL"
    )
    params: list = [fi_done]
    if brand_id is not None:
        query += " AND l.brand_id = ?"
        params.append(brand_id)
    rows = conn.execute(query, params).fetchall()

    weekly: dict[str, int] = defaultdict(int)
    for r in rows:
        moved = datetime.fromisoformat(r["moved_at"])
        year, week, _ = moved.isocalendar()
        weekly[f"{year}-W{week:02d}"] += r["qty"]
    return [{"week": week, "qty": qty} for week, qty in sorted(weekly.items())]


def wip_over_time(conn: sqlite3.Connection, brand_id: int | None = None) -> list[dict]:
    query = "SELECT m.from_stage_id, m.to_stage_id, m.qty, m.moved_at FROM movements m"
    params: list = []
    if brand_id is not None:
        query += " JOIN lots l ON l.id = m.lot_id WHERE l.brand_id = ?"
        params.append(brand_id)
    query += " ORDER BY m.moved_at ASC, m.id ASC"

    movements = conn.execute(query, params).fetchall()
    stage_names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM stages")}

    current: dict[int, int] = defaultdict(int)
    snapshots: list[dict] = []
    last_date = None
    for m in movements:
        moved_date = m["moved_at"][:10]
        if m["from_stage_id"] is not None:
            current[m["from_stage_id"]] -= m["qty"]
        current[m["to_stage_id"]] += m["qty"]

        by_stage = {stage_names[sid]: qty for sid, qty in current.items() if qty > 0}
        if moved_date != last_date:
            snapshots.append({"date": moved_date, "by_stage": by_stage})
            last_date = moved_date
        else:
            snapshots[-1] = {"date": moved_date, "by_stage": by_stage}
    return snapshots


def fi_date_risk(conn: sqlite3.Connection, brand_id: int | None = None) -> list[dict]:
    """Estimate: predicted completion = today + sum(avg days per remaining stage).
    Worthless until ~2 months of movement history exists - always label as an estimate."""
    stage_avgs = avg_days_per_stage(conn, brand_id=brand_id)
    stages = conn.execute("SELECT id, name, rank FROM stages ORDER BY rank").fetchall()
    rank_by_id = {s["id"]: s["rank"] for s in stages}
    name_by_rank = {s["rank"]: s["name"] for s in stages}

    query = (
        "SELECT l.id, l.ct_number, l.fi_date, b.name AS brand_name "
        "FROM lots l JOIN brands b ON b.id = l.brand_id "
        "WHERE l.closed_at IS NULL AND l.fi_date IS NOT NULL"
    )
    params: list = []
    if brand_id is not None:
        query += " AND b.id = ?"
        params.append(brand_id)
    lots = conn.execute(query, params).fetchall()

    today = date.today()
    result = []
    for lot in lots:
        positions = conn.execute(
            "SELECT stage_id FROM positions WHERE lot_id = ?", (lot["id"],)
        ).fetchall()
        if not positions:
            continue
        current_rank = max(rank_by_id[p["stage_id"]] for p in positions)
        remaining_days = sum(
            stage_avgs.get(name_by_rank[r], 0) for r in range(1, current_rank)
        )
        try:
            fi_date = date.fromisoformat(lot["fi_date"][:10])
        except (ValueError, TypeError):
            continue
        predicted = today + timedelta(days=remaining_days)
        result.append(
            {
                "lot_id": lot["id"],
                "ct_number": lot["ct_number"],
                "brand_name": lot["brand_name"],
                "fi_date": fi_date.isoformat(),
                "predicted_completion": predicted.isoformat(),
                "at_risk": predicted > fi_date,
            }
        )
    result.sort(key=lambda r: r["fi_date"])
    return result


def summary_kpis(conn: sqlite3.Connection, brand_id: int | None = None) -> dict:
    """Headline numbers for the KPI row: where things stand right now."""
    brand_filter = " AND brand_id = ?" if brand_id is not None else ""
    params = [brand_id] if brand_id is not None else []

    open_lots_count, pieces_in_pipeline = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM(total_qty), 0) FROM lots "
        f"WHERE closed_at IS NULL{brand_filter}",
        params,
    ).fetchone()

    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=now.isoweekday() - 1)).strftime("%Y-%m-%d")
    shipped_this_week = conn.execute(
        f"SELECT COALESCE(SUM(total_qty), 0) FROM lots "
        f"WHERE closed_at IS NOT NULL AND substr(closed_at, 1, 10) >= ?{brand_filter}",
        [week_start, *params],
    ).fetchone()[0]

    closed_query = f"SELECT created_at, closed_at FROM lots WHERE closed_at IS NOT NULL{brand_filter}"
    closed_lots = conn.execute(closed_query, params).fetchall()
    cycle_days = [
        (datetime.fromisoformat(r["closed_at"]) - datetime.fromisoformat(r["created_at"])).days
        for r in closed_lots
    ]
    avg_cycle_time_days = round(sum(cycle_days) / len(cycle_days), 1) if len(cycle_days) >= 3 else None

    return {
        "open_lots_count": open_lots_count,
        "pieces_in_pipeline": pieces_in_pipeline,
        "shipped_this_week": shipped_this_week,
        "avg_cycle_time_days": avg_cycle_time_days,
        "closed_lot_count": len(closed_lots),
    }
