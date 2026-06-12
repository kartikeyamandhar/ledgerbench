"""Build the tiny_shop fixture warehouse deterministically (no dbt required)."""

from __future__ import annotations

import random
from pathlib import Path

import duckdb


def build(path: str | Path, seed: int = 7) -> Path:
    """Create tiny.duckdb with ~260 deterministic rows; returns the path."""
    db = Path(path)
    db.unlink(missing_ok=True)
    con = duckdb.connect(str(db))
    rng = random.Random(seed)
    con.execute("CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, region VARCHAR)")
    con.execute(
        "CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER,"
        " order_ts TIMESTAMP, amount DECIMAL(10,2), status VARCHAR, refunded BOOLEAN)"
    )
    con.execute(
        "CREATE TABLE order_items (item_id INTEGER PRIMARY KEY, order_id INTEGER, quantity INTEGER)"
    )
    regions = ["NA", "EU", "APAC", None]
    for cid in range(1, 21):
        con.execute("INSERT INTO customers VALUES (?, ?)", [cid, rng.choice(regions)])
    item_id = 1
    for oid in range(1, 81):
        month = rng.randint(1, 5)
        day = rng.randint(1, 28)
        status = rng.choice(["completed"] * 7 + ["pending"] * 2 + ["refunded"])
        refunded = status == "refunded" or rng.random() < 0.05
        con.execute(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)",
            [
                oid,
                rng.randint(1, 20),
                f"2026-0{month}-{day:02d} {rng.randint(0, 23):02d}:00:00",
                round(rng.uniform(20, 400), 2),
                status,
                refunded,
            ],
        )
        for _ in range(rng.randint(1, 4)):
            con.execute(
                "INSERT INTO order_items VALUES (?, ?, ?)",
                [item_id, oid, rng.randint(1, 5)],
            )
            item_id += 1
    con.close()
    return db


if __name__ == "__main__":
    print(build(Path(__file__).parent / "tiny.duckdb"))
