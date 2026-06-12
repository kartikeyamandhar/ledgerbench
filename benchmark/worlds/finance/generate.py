"""Seeded, deterministic generator for the finance world.

Builds accounts, a fiscal calendar offset to a February start, transactions (UTC
timestamps), and double-entry ledger entries (two per transaction -> the
transactions -> ledger_entries fan-out). Carries gross-vs-net revenue ambiguity,
status exclusions, planted null memos, and one logical duplicate transaction. All
randomness flows through one seeded ``Random`` -- no wall-clock, no network -- so a
given seed reproduces byte-identical data. Row counts stay within the 50k-100k band.
"""

from __future__ import annotations

import datetime
import random
from decimal import Decimal
from typing import Any

N_ACCOUNTS = 500
N_TRANSACTIONS = 18_000
FISCAL_START_MONTH = 2  # fiscal year starts in February (the offset precondition)
FISCAL_YEARS = (2025, 2026)

ACCOUNT_TYPES = ("asset", "liability", "revenue", "expense")
CURRENCIES = ("USD", "EUR", "GBP")
CATEGORIES = ("sales", "refund", "fee", "payout", "adjustment", "interest")
STATUSES = ("posted", "pending", "void")

_EPOCH = datetime.datetime(2025, 2, 1, 0, 0, 0)  # UTC base, aligned to the fiscal-year start


def _month_end(year: int, month: int) -> datetime.date:
    """Return the last calendar day of ``year``-``month``."""
    if month == 12:
        return datetime.date(year, 12, 31)
    return datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)


def _fiscal_periods() -> list[tuple[int, int, int, datetime.date, datetime.date]]:
    """Return 12 monthly periods per fiscal year, offset to a February start."""
    periods = []
    pid = 0
    for fiscal_year in FISCAL_YEARS:
        for offset in range(12):
            month = (FISCAL_START_MONTH - 1 + offset) % 12 + 1
            year = fiscal_year + (FISCAL_START_MONTH - 1 + offset) // 12
            pid += 1
            start = datetime.date(year, month, 1)
            periods.append((pid, fiscal_year, offset + 1, start, _month_end(year, month)))
    return periods


def build(con: Any, seed: int) -> None:
    """Populate the finance schema deterministically from ``seed``."""
    rng = random.Random(seed)
    con.execute("BEGIN TRANSACTION")  # one transaction: bulk-load is far faster than per-statement

    accounts = [
        (aid, f"Account {aid}", rng.choice(ACCOUNT_TYPES), rng.choice(CURRENCIES))
        for aid in range(1, N_ACCOUNTS + 1)
    ]
    con.executemany("INSERT INTO accounts VALUES (?, ?, ?, ?)", accounts)

    con.executemany("INSERT INTO fiscal_periods VALUES (?, ?, ?, ?, ?)", _fiscal_periods())

    # Gross revenue sums every transaction; net revenue excludes void and pending.
    transactions = []
    for tid in range(1, N_TRANSACTIONS + 1):
        account_id = rng.randint(1, N_ACCOUNTS)
        txn_ts = _EPOCH + datetime.timedelta(seconds=rng.randint(0, 720 * 86_400 - 1))
        amount = Decimal(rng.randint(100, 1_000_000)) / 100
        category = rng.choice(CATEGORIES)
        # ~5% planted null memos (documented irregularity).
        memo = None if rng.random() < 0.05 else f"ref-{tid:06d}"
        status = rng.choices(STATUSES, weights=(75, 15, 10))[0]
        transactions.append((tid, account_id, txn_ts, amount, category, memo, status))
    # One logical duplicate transaction (same account/ts/amount, fresh id; documented).
    src = transactions[rng.randint(0, N_TRANSACTIONS - 1)]
    transactions.append((N_TRANSACTIONS + 1, src[1], src[2], src[3], src[4], src[5], src[6]))
    con.executemany("INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?)", transactions)

    # Double-entry: one debit row and one credit row per transaction (the fan-out).
    entries = []
    eid = 0
    zero = Decimal("0.00")
    for tid, account_id, _ts, amount, _cat, _memo, _status in transactions:
        contra_account = rng.randint(1, N_ACCOUNTS)
        eid += 1
        entries.append((eid, tid, account_id, amount, zero))
        eid += 1
        entries.append((eid, tid, contra_account, zero, amount))
    con.executemany("INSERT INTO ledger_entries VALUES (?, ?, ?, ?, ?)", entries)

    con.execute("COMMIT")
