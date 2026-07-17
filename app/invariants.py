import sqlite3

INVARIANT_QUERY = """
SELECT l.id, l.ct_number, l.total_qty, COALESCE(SUM(p.qty), 0) AS in_stages
FROM lots l
LEFT JOIN positions p ON p.lot_id = l.id
WHERE l.closed_at IS NULL
GROUP BY l.id
HAVING in_stages <> l.total_qty
"""


class InvariantViolation(Exception):
    def __init__(self, rows: list[sqlite3.Row]):
        self.rows = rows
        detail = "; ".join(
            f"lot {r['ct_number']} (id={r['id']}): total_qty={r['total_qty']} but "
            f"in_stages={r['in_stages']}"
            for r in rows
        )
        super().__init__(f"Invariant violated for {len(rows)} lot(s): {detail}")


def check_invariants(conn: sqlite3.Connection) -> None:
    rows = conn.execute(INVARIANT_QUERY).fetchall()
    if rows:
        raise InvariantViolation(rows)
