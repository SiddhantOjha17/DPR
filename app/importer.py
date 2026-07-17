import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import openpyxl

from app import db
from app.stages import map_status_to_stage

# Per-sheet 1-based column indices, from spec section 7.1.
# ct, code, fabric, qty, status, fi_date, fabric_date (fabric_date is None where absent)
SHEET_COLUMNS: dict[str, dict[str, int | None]] = {
    "SPYKAR": {"ct": 1, "code": 4, "wash": 5, "fabric": 6, "qty": 7, "status": 8, "fi_date": 9, "fabric_date": None},
    "MONTE CARLO": {"ct": 1, "code": 4, "wash": None, "fabric": 5, "qty": 6, "status": 7, "fi_date": 8, "fabric_date": None},
    "PEPE": {"ct": 1, "code": 4, "wash": None, "fabric": 5, "qty": 6, "status": 7, "fi_date": 8, "fabric_date": None},
    "KKCL": {"ct": 1, "code": 4, "wash": None, "fabric": 5, "qty": 6, "status": 7, "fi_date": 8, "fabric_date": None},
    "RAYMOND": {"ct": 1, "sub_brand": 2, "code": 3, "wash": None, "fabric": 4, "qty": 5, "status": 6, "fi_date": 7, "fabric_date": 8},
    "BENETTON": {"ct": 1, "code": 3, "wash": None, "fabric": 4, "qty": 5, "status": 6, "fi_date": 7, "fabric_date": 8},
    "ARVIND": {"ct": 1, "code": 3, "wash": None, "fabric": 4, "qty": 5, "status": 6, "fi_date": 7, "fabric_date": 8},
}

# The exact numbers the one known JUNE_DPR.xlsx fixture reconciles to. These are
# NOT enforced at runtime (a repeat import of a different, later sheet would have
# different real totals) - they exist purely so the test suite can pin the
# importer's correctness against a known-good fixture. See
# tests/test_importer_reconciliation.py.
EXPECTED_TOTAL_LOTS = 135
EXPECTED_TOTAL_PIECES = 90908
EXPECTED_PER_BRAND = {
    "SPYKAR": 35750,
    "MONTE CARLO": 9720,
    "PEPE": 10448,
    "KKCL": 6311,
    "RAYMOND": 13071,
    "BENETTON": 4908,
    "ARVIND": 10700,
}


@dataclass
class ImportResult:
    total_lots: int = 0
    total_pieces: int = 0
    per_brand: dict[str, int] = field(default_factory=dict)
    unmapped_statuses: list[tuple[str, str, str]] = field(default_factory=list)  # (sheet, ct, raw_status)
    skipped_duplicates: list[tuple[str, str]] = field(default_factory=list)  # (sheet, ct)
    replaced: bool = False


def _cell(row: tuple, col: int | None):
    if col is None or col - 1 >= len(row):
        return None
    return row[col - 1]


def _as_date(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def import_workbook(
    path: str,
    conn: sqlite3.Connection,
    *,
    wipe_existing: bool = False,
    moved_by: int | None = None,
) -> ImportResult:
    """Import every brand sheet from the workbook at `path`.

    Rows whose status text doesn't map to a known stage are skipped and listed in
    `unmapped_statuses`. Rows whose CT number already exists in the app are always
    skipped and listed in `skipped_duplicates` - never silently duplicated or
    overwritten. Pass `wipe_existing=True` to clear all lots/positions/movements
    first (a full "Replace" import); the default is an additive "Add" import.

    There is no hard-coded expected-totals gate here - the caller (the /import
    route) shows `ImportResult`'s own computed totals so the owner can eyeball them
    against the paper sheet. See EXPECTED_* above for why: those numbers are only
    ever correct for the one specific fixture file, not for repeat imports of an
    updated sheet.
    """
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)

    result = ImportResult()
    seed_date = datetime.now(timezone.utc).isoformat()

    with db.transaction(conn):
        if wipe_existing:
            conn.execute("DELETE FROM lots")
            result.replaced = True

        brand_ids = {
            row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM brands")
        }
        stage_ids = {
            row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM stages")
        }
        sub_brand_ids = {
            (row["brand_id"], row["name"].upper()): row["id"]
            for row in conn.execute("SELECT id, brand_id, name FROM sub_brands")
        }
        existing_cts = {
            row["ct_number"] for row in conn.execute("SELECT ct_number FROM lots")
        }

        for sheet_name, columns in SHEET_COLUMNS.items():
            ws = wb[sheet_name]
            brand_id = brand_ids[sheet_name]
            sheet_pieces = 0

            for row in ws.iter_rows(min_row=3, values_only=True):
                qty = _cell(row, columns["qty"])
                if not isinstance(qty, (int, float)):
                    continue
                status_raw = _cell(row, columns["status"])
                if not status_raw or "total" in str(status_raw).lower():
                    continue

                ct = _cell(row, columns["ct"])
                ct_number = str(ct) if ct is not None else ""

                # Some real rows (a few ARVIND/PEPE lots) genuinely have a blank CT
                # number - never treat blanks as duplicates of each other.
                if ct_number and ct_number in existing_cts:
                    result.skipped_duplicates.append((sheet_name, ct_number))
                    continue

                stage_name = map_status_to_stage(str(status_raw))
                if stage_name is None:
                    result.unmapped_statuses.append((sheet_name, ct_number, str(status_raw)))
                    continue

                sub_brand_id = None
                sub_brand_col = columns.get("sub_brand")
                if sub_brand_col is not None:
                    raw_sub = _cell(row, sub_brand_col)
                    if raw_sub:
                        sub_brand_id = sub_brand_ids.get((brand_id, str(raw_sub).strip().upper()))

                wash_col = columns.get("wash")
                wash = _cell(row, wash_col) if wash_col is not None else None

                cur = conn.execute(
                    "INSERT INTO lots "
                    "(brand_id, sub_brand_id, ct_number, material_code, fabric, wash, "
                    "total_qty, fi_date, fabric_date, remark, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        brand_id,
                        sub_brand_id,
                        ct_number,
                        str(_cell(row, columns["code"]) or "") or None,
                        str(_cell(row, columns["fabric"]) or "") or None,
                        str(wash) if wash else None,
                        int(qty),
                        _as_date(_cell(row, columns["fi_date"])),
                        _as_date(_cell(row, columns.get("fabric_date"))),
                        str(status_raw),
                        seed_date,
                    ),
                )
                lot_id = cur.lastrowid
                stage_id = stage_ids[stage_name]
                conn.execute(
                    "INSERT INTO positions (lot_id, stage_id, qty, entered_at) VALUES (?, ?, ?, ?)",
                    (lot_id, stage_id, int(qty), seed_date),
                )
                conn.execute(
                    "INSERT INTO movements "
                    "(lot_id, from_stage_id, to_stage_id, qty, moved_at, moved_by, note) "
                    "VALUES (?, NULL, ?, ?, ?, ?, ?)",
                    (lot_id, stage_id, int(qty), seed_date, moved_by, "opening import"),
                )

                if ct_number:
                    existing_cts.add(ct_number)
                result.total_lots += 1
                result.total_pieces += int(qty)
                sheet_pieces += int(qty)

            result.per_brand[sheet_name] = sheet_pieces

    return result
