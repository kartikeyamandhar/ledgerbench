"""Seeded, deterministic generator for the saas world.

Builds customers, subscriptions, users, orders, shipments, and events carrying the
preconditions the trap taxonomy needs: refund/status exclusions on revenue, an
orders -> shipments fan-out, ambiguous activity windows, planted null regions, and
logical duplicate events. All randomness flows through one seeded ``Random``; there
is no wall-clock or network use, so regeneration is byte-identical for a given seed
(verified by the world-digest tests). Row counts stay within the 50k-100k band.
"""

from __future__ import annotations

import datetime
import random
from decimal import Decimal
from typing import Any

N_CUSTOMERS = 2_000
N_ORDERS = 12_000
N_EVENTS = 25_000
N_DUPLICATE_EVENTS = 200

PLANS = ("starter", "pro", "enterprise")
PLAN_MRR = {
    "starter": Decimal("29.00"),
    "pro": Decimal("99.00"),
    "enterprise": Decimal("499.00"),
}
REGIONS = ("NA", "EMEA", "APAC", "LATAM")
CARRIERS = ("ups", "fedex", "dhl", "usps")
EVENT_TYPES = ("login", "view", "click", "export", "invite")
ORDER_STATUSES = ("completed", "pending", "refunded")

_EPOCH = datetime.datetime(2025, 1, 1, 0, 0, 0)  # UTC base for all timestamps


def _ts(rng: random.Random, max_days: int) -> datetime.datetime:
    """Return a deterministic UTC timestamp within ``max_days`` of the epoch."""
    return _EPOCH + datetime.timedelta(seconds=rng.randint(0, max_days * 86_400 - 1))


def _date(rng: random.Random, max_days: int) -> datetime.date:
    """Return a deterministic date within ``max_days`` of the epoch."""
    return (_EPOCH + datetime.timedelta(days=rng.randint(0, max_days))).date()


def build(con: Any, seed: int) -> None:
    """Populate the saas schema deterministically from ``seed``."""
    rng = random.Random(seed)
    con.execute("BEGIN TRANSACTION")  # one transaction: bulk-load is far faster than per-statement

    customers = []
    for cid in range(1, N_CUSTOMERS + 1):
        plan = rng.choice(PLANS)
        # ~3% planted null regions (documented irregularity).
        region = None if rng.random() < 0.03 else rng.choice(REGIONS)
        customers.append((cid, f"Customer {cid}", plan, region, _date(rng, 700)))
    con.executemany("INSERT INTO customers VALUES (?, ?, ?, ?, ?)", customers)

    subscriptions = []
    for cid in range(1, N_CUSTOMERS + 1):
        plan = customers[cid - 1][2]
        canceled = rng.random() < 0.2
        started = _date(rng, 500)
        canceled_on = started + datetime.timedelta(days=rng.randint(30, 400)) if canceled else None
        status = "canceled" if canceled else "active"
        subscriptions.append((cid, cid, plan, PLAN_MRR[plan], status, started, canceled_on))
    con.executemany("INSERT INTO subscriptions VALUES (?, ?, ?, ?, ?, ?, ?)", subscriptions)

    users = []
    uid = 0
    for cid in range(1, N_CUSTOMERS + 1):
        for _ in range(rng.randint(1, 3)):
            uid += 1
            users.append((uid, cid, f"user{uid}@example.com", _date(rng, 700)))
    con.executemany("INSERT INTO users VALUES (?, ?, ?, ?)", users)
    n_users = uid

    # Revenue lives on orders; status drives the refunded flag. The true revenue is
    # completed orders that were not refunded.
    orders = []
    for oid in range(1, N_ORDERS + 1):
        cid = rng.randint(1, N_CUSTOMERS)
        status = rng.choices(ORDER_STATUSES, weights=(70, 20, 10))[0]
        amount = Decimal(rng.randint(500, 50_000)) / 100
        orders.append((oid, cid, _ts(rng, 500), amount, status, status == "refunded"))
    con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)", orders)

    # 1-3 shipments per completed order: the orders -> shipments fan-out (fan trap).
    shipments = []
    sid = 0
    for oid, _cid, order_ts, _amount, status, _refunded in orders:
        if status != "completed":
            continue
        for _ in range(rng.randint(1, 3)):
            sid += 1
            shipped = order_ts + datetime.timedelta(days=rng.randint(1, 10))
            shipments.append((sid, oid, shipped, rng.choice(CARRIERS)))
    con.executemany("INSERT INTO shipments VALUES (?, ?, ?, ?)", shipments)

    events = []
    for eid in range(1, N_EVENTS + 1):
        events.append((eid, rng.randint(1, n_users), _ts(rng, 500), rng.choice(EVENT_TYPES)))
    # Logical duplicate events: same user/timestamp/type, fresh id (documented).
    for k in range(N_DUPLICATE_EVENTS):
        source = events[rng.randint(0, N_EVENTS - 1)]
        events.append((N_EVENTS + k + 1, source[1], source[2], source[3]))
    con.executemany("INSERT INTO events VALUES (?, ?, ?, ?)", events)

    con.execute("COMMIT")
