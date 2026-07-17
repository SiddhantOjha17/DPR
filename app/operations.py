import sqlite3
from datetime import datetime, timezone

from app import db


class MoveError(Exception):
    pass


class UndoError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stage_name(conn: sqlite3.Connection, stage_id: int) -> str:
    row = conn.execute("SELECT name FROM stages WHERE id = ?", (stage_id,)).fetchone()
    return row["name"] if row else f"stage {stage_id}"


def _apply_move(
    conn: sqlite3.Connection,
    *,
    lot_id: int,
    from_stage_id: int,
    to_stage_id: int,
    qty: int,
    moved_at: str,
    moved_by: int | None,
    note: str | None,
    reverses_id: int | None,
) -> int:
    source = conn.execute(
        "SELECT qty FROM positions WHERE lot_id = ? AND stage_id = ?",
        (lot_id, from_stage_id),
    ).fetchone()
    available = source["qty"] if source else 0
    if available < qty:
        raise MoveError(
            f"Only {available} pieces are in {_stage_name(conn, from_stage_id)}"
        )

    if available == qty:
        conn.execute(
            "DELETE FROM positions WHERE lot_id = ? AND stage_id = ?",
            (lot_id, from_stage_id),
        )
    else:
        conn.execute(
            "UPDATE positions SET qty = qty - ? WHERE lot_id = ? AND stage_id = ?",
            (qty, lot_id, from_stage_id),
        )

    dest = conn.execute(
        "SELECT qty, entered_at FROM positions WHERE lot_id = ? AND stage_id = ?",
        (lot_id, to_stage_id),
    ).fetchone()
    if dest is None:
        conn.execute(
            "INSERT INTO positions (lot_id, stage_id, qty, entered_at) VALUES (?, ?, ?, ?)",
            (lot_id, to_stage_id, qty, moved_at),
        )
    else:
        new_entered_at = min(dest["entered_at"], moved_at)
        conn.execute(
            "UPDATE positions SET qty = qty + ?, entered_at = ? "
            "WHERE lot_id = ? AND stage_id = ?",
            (qty, new_entered_at, lot_id, to_stage_id),
        )

    cur = conn.execute(
        "INSERT INTO movements "
        "(lot_id, from_stage_id, to_stage_id, qty, moved_at, moved_by, note, reverses_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (lot_id, from_stage_id, to_stage_id, qty, moved_at, moved_by, note, reverses_id),
    )
    return cur.lastrowid


def create_lot(
    conn: sqlite3.Connection,
    *,
    brand_id: int,
    ct_number: str,
    total_qty: int,
    starting_stage_id: int,
    sub_brand_id: int | None = None,
    material_code: str | None = None,
    fabric: str | None = None,
    wash: str | None = None,
    fi_date: str | None = None,
    fabric_date: str | None = None,
    remark: str | None = None,
    moved_by: int | None = None,
    entered_at: str | None = None,
) -> int:
    entered_at = entered_at or _now()
    with db.transaction(conn):
        cur = conn.execute(
            "INSERT INTO lots "
            "(brand_id, sub_brand_id, ct_number, material_code, fabric, wash, "
            "total_qty, fi_date, fabric_date, remark, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                brand_id,
                sub_brand_id,
                ct_number,
                material_code,
                fabric,
                wash,
                total_qty,
                fi_date,
                fabric_date,
                remark,
                entered_at,
            ),
        )
        lot_id = cur.lastrowid
        conn.execute(
            "INSERT INTO positions (lot_id, stage_id, qty, entered_at) VALUES (?, ?, ?, ?)",
            (lot_id, starting_stage_id, total_qty, entered_at),
        )
        conn.execute(
            "INSERT INTO movements "
            "(lot_id, from_stage_id, to_stage_id, qty, moved_at, moved_by, note) "
            "VALUES (?, NULL, ?, ?, ?, ?, ?)",
            (lot_id, starting_stage_id, total_qty, entered_at, moved_by, None),
        )
        return lot_id


def move_pieces(
    conn: sqlite3.Connection,
    *,
    lot_id: int,
    from_stage_id: int,
    to_stage_id: int,
    qty: int,
    moved_by: int | None = None,
    note: str | None = None,
    moved_at: str | None = None,
) -> int:
    moved_at = moved_at or _now()
    with db.transaction(conn):
        return _apply_move(
            conn,
            lot_id=lot_id,
            from_stage_id=from_stage_id,
            to_stage_id=to_stage_id,
            qty=qty,
            moved_at=moved_at,
            moved_by=moved_by,
            note=note,
            reverses_id=None,
        )


def undo_movement(
    conn: sqlite3.Connection,
    *,
    movement_id: int,
    moved_by: int | None = None,
    note: str | None = None,
    moved_at: str | None = None,
) -> int | None:
    """Returns the new compensating movement id, or None if the lot was deleted
    (undoing its sole opening movement)."""
    moved_at = moved_at or _now()

    movement = conn.execute(
        "SELECT * FROM movements WHERE id = ?", (movement_id,)
    ).fetchone()
    if movement is None:
        raise UndoError(f"No such movement: {movement_id}")

    already_reversed = conn.execute(
        "SELECT 1 FROM movements WHERE reverses_id = ?", (movement_id,)
    ).fetchone()
    if already_reversed:
        raise UndoError("This movement has already been undone.")

    if movement["from_stage_id"] is None:
        lot_id = movement["lot_id"]
        movement_count = conn.execute(
            "SELECT COUNT(*) AS n FROM movements WHERE lot_id = ?", (lot_id,)
        ).fetchone()["n"]
        if movement_count != 1:
            raise UndoError(
                "Cannot undo the opening move: later movements exist on this lot."
            )
        with db.transaction(conn):
            conn.execute("DELETE FROM lots WHERE id = ?", (lot_id,))
        return None

    to_stage_qty = conn.execute(
        "SELECT qty FROM positions WHERE lot_id = ? AND stage_id = ?",
        (movement["lot_id"], movement["to_stage_id"]),
    ).fetchone()
    available = to_stage_qty["qty"] if to_stage_qty else 0
    if available < movement["qty"]:
        raise UndoError(
            f"Only {available} of those {movement['qty']} pieces are still in "
            f"{_stage_name(conn, movement['to_stage_id'])}. Undo the later moves first."
        )

    with db.transaction(conn):
        return _apply_move(
            conn,
            lot_id=movement["lot_id"],
            from_stage_id=movement["to_stage_id"],
            to_stage_id=movement["from_stage_id"],
            qty=movement["qty"],
            moved_at=moved_at,
            moved_by=moved_by,
            note=note,
            reverses_id=movement_id,
        )


def update_lot_details(
    conn: sqlite3.Connection,
    *,
    lot_id: int,
    sub_brand_id: int | None = None,
    remark: str | None = None,
    material_code: str | None = None,
    fabric: str | None = None,
    wash: str | None = None,
    fi_date: str | None = None,
    fabric_date: str | None = None,
) -> None:
    conn.execute(
        "UPDATE lots SET sub_brand_id = ?, remark = ?, material_code = ?, fabric = ?, "
        "wash = ?, fi_date = ?, fabric_date = ? WHERE id = ?",
        (sub_brand_id, remark, material_code, fabric, wash, fi_date, fabric_date, lot_id),
    )
    conn.commit()


def mark_shipped(conn: sqlite3.Connection, *, lot_id: int) -> None:
    positions = conn.execute(
        "SELECT stage_id FROM positions WHERE lot_id = ?", (lot_id,)
    ).fetchall()
    fi_done = conn.execute(
        "SELECT id FROM stages WHERE name = 'FI Done'"
    ).fetchone()["id"]
    if not positions or any(p["stage_id"] != fi_done for p in positions):
        raise MoveError("Lot is not fully at FI Done yet.")
    with db.transaction(conn):
        conn.execute(
            "UPDATE lots SET closed_at = ? WHERE id = ?", (_now(), lot_id)
        )


def reopen_lot(conn: sqlite3.Connection, *, lot_id: int) -> None:
    """Undo a shipment: clears closed_at so the lot reappears on the main screen
    at whatever stage its positions still say (normally FI Done, untouched since
    mark_shipped never moves pieces, only stamps the lot as closed)."""
    lot = conn.execute("SELECT closed_at FROM lots WHERE id = ?", (lot_id,)).fetchone()
    if lot is None:
        raise MoveError(f"No such lot: {lot_id}")
    if lot["closed_at"] is None:
        raise MoveError("Lot is not shipped.")
    with db.transaction(conn):
        conn.execute("UPDATE lots SET closed_at = NULL WHERE id = ?", (lot_id,))


def days_in_stage_current(conn: sqlite3.Connection, lot_id: int) -> list[dict]:
    now = datetime.now(timezone.utc)
    rows = conn.execute(
        "SELECT p.stage_id, s.name AS stage_name, p.qty, p.entered_at "
        "FROM positions p JOIN stages s ON s.id = p.stage_id "
        "WHERE p.lot_id = ? ORDER BY s.rank",
        (lot_id,),
    ).fetchall()
    result = []
    for r in rows:
        entered = datetime.fromisoformat(r["entered_at"])
        result.append(
            {
                "stage_id": r["stage_id"],
                "stage_name": r["stage_name"],
                "qty": r["qty"],
                "entered_at": r["entered_at"],
                "days": (now - entered).days,
            }
        )
    return result


def days_in_stage_historical(conn: sqlite3.Connection, lot_id: int) -> list[dict]:
    movements = conn.execute(
        "SELECT from_stage_id, to_stage_id, moved_at FROM movements "
        "WHERE lot_id = ? ORDER BY moved_at ASC",
        (lot_id,),
    ).fetchall()

    entered: dict[int, str] = {}
    left: dict[int, str] = {}
    for m in movements:
        to_stage = m["to_stage_id"]
        if to_stage not in entered:
            entered[to_stage] = m["moved_at"]
        if m["from_stage_id"] is not None:
            left[m["from_stage_id"]] = m["moved_at"]

    stage_names = {
        r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM stages")
    }
    now = datetime.now(timezone.utc)
    summary = []
    for stage_id, first_entered in entered.items():
        last_left = left.get(stage_id)
        start = datetime.fromisoformat(first_entered)
        end = datetime.fromisoformat(last_left) if last_left else now
        summary.append(
            {
                "stage_id": stage_id,
                "stage_name": stage_names.get(stage_id, f"stage {stage_id}"),
                "first_entered": first_entered,
                "last_left": last_left,
                "total_days": (end - start).days,
            }
        )
    summary.sort(key=lambda s: s["first_entered"])
    return summary
