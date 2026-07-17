import sqlite3

STAGES = [
    (1, "FI Done"),
    (2, "Under Finishing"),
    (3, "Under Loading"),
    (4, "Under Washing"),
    (5, "Under Assembly"),
    (6, "Under Sewing"),
    (7, "Under Embroidery"),
    (8, "Under Cutting"),
    (9, "Issued for Cutting"),
    (10, "Bulk Pattern"),
    (11, "Size Set / PP Approval"),
    (12, "Under Shrinkage"),
    (13, "Fabric Received"),
]

BRANDS = ["ARVIND", "BENETTON", "KKCL", "MONTE CARLO", "PEPE", "RAYMOND", "SPYKAR"]

RAYMOND_SUB_BRANDS = ["CP", "PARX", "PA"]

DEFAULT_USER = "Owner"


def seed_if_empty(conn: sqlite3.Connection) -> None:
    (count,) = conn.execute("SELECT COUNT(*) FROM stages").fetchone()
    if count > 0:
        return

    conn.executemany(
        "INSERT INTO stages (rank, name) VALUES (?, ?)",
        [(rank, name) for rank, name in STAGES],
    )

    for name in BRANDS:
        conn.execute("INSERT INTO brands (name) VALUES (?)", (name,))

    (raymond_id,) = conn.execute(
        "SELECT id FROM brands WHERE name = 'RAYMOND'"
    ).fetchone()
    conn.executemany(
        "INSERT INTO sub_brands (brand_id, name) VALUES (?, ?)",
        [(raymond_id, name) for name in RAYMOND_SUB_BRANDS],
    )

    conn.execute("INSERT INTO users (name) VALUES (?)", (DEFAULT_USER,))

    conn.commit()
