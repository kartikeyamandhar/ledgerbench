"""Unit tests for the grain checker: repairs, axis mapping, empirical helper."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from ledgerbench.ingestion.rulebook import load_rulebook
from ledgerbench.scorer.grain_check import (
    check_grain,
    empirical_inflation,
    grain_axis_result,
)

_REPO = Path(__file__).resolve().parents[2]
SAAS = load_rulebook(_REPO / "benchmark/worlds/saas/rulebook.yaml").to_grain_model()
FINANCE = load_rulebook(_REPO / "benchmark/worlds/finance/rulebook.yaml").to_grain_model()

# The canonical fan fixtures and their pre-aggregation repairs. The property:
# wrapping the many side in a keyed pre-aggregation flips unsafe -> safe.
CANONICAL_PAIRS = [
    (
        SAAS,
        "SELECT sum(o.amount) FROM orders o JOIN shipments s ON o.order_id = s.order_id",
        """SELECT sum(o.amount) FROM orders o
           JOIN (SELECT order_id FROM shipments GROUP BY order_id) s
             ON o.order_id = s.order_id""",
    ),
    (
        FINANCE,
        """SELECT sum(t.amount) FROM transactions t
           JOIN ledger_entries l ON t.transaction_id = l.transaction_id""",
        """SELECT sum(t.amount) FROM transactions t
           JOIN (SELECT transaction_id FROM ledger_entries GROUP BY transaction_id) l
             ON t.transaction_id = l.transaction_id""",
    ),
]


@pytest.mark.parametrize("gm, unsafe_sql, repaired_sql", CANONICAL_PAIRS)
def test_preaggregation_flips_unsafe_to_safe(gm, unsafe_sql, repaired_sql) -> None:
    assert check_grain(unsafe_sql, gm).status == "unsafe"
    assert check_grain(repaired_sql, gm).status == "safe"


@pytest.mark.parametrize(
    "alias_a, alias_b",
    [("o", "s"), ("ord", "shp"), ('"Orders Alias"', '"Ship Alias"')],
)
def test_verdict_is_alias_invariant(alias_a, alias_b) -> None:
    sql = (
        f"SELECT sum({alias_a}.amount) FROM orders AS {alias_a} "
        f"JOIN shipments AS {alias_b} ON {alias_a}.order_id = {alias_b}.order_id"
    )
    assert check_grain(sql, SAAS).status == "unsafe"


def test_unparseable_sql_is_unknown() -> None:
    result = check_grain("SELEKT amount FORM orders", SAAS)
    assert result.status == "unknown"
    assert result.unsupported is not None


def test_non_select_is_unknown() -> None:
    assert check_grain("UPDATE orders SET amount = 0", SAAS).status == "unknown"


def test_deep_nesting_reason_is_named() -> None:
    sql = "SELECT sum(a) FROM (SELECT amount AS a FROM (SELECT amount FROM orders) x) y"
    result = check_grain(sql, SAAS)
    assert result.status == "unknown"
    assert result.unsupported == "nesting deeper than one level"


def test_evidence_names_the_offending_aggregate() -> None:
    result = check_grain(
        "SELECT sum(o.amount) FROM orders o JOIN shipments s ON o.order_id = s.order_id",
        SAAS,
    )
    assert result.status == "unsafe"
    assert any("amount" in agg.lower() for agg in result.offending_aggregates)
    assert result.fan_out_paths[0].from_table == "orders"
    assert result.fan_out_paths[0].to_table == "shipments"


def test_axis_mapping() -> None:
    unsafe = check_grain(
        "SELECT sum(o.amount) FROM orders o JOIN shipments s ON o.order_id = s.order_id",
        SAAS,
    )
    safe = check_grain("SELECT sum(amount) FROM orders", SAAS)
    unknown = check_grain("SELECT sum(amount) OVER () FROM orders", SAAS)

    assert grain_axis_result(unsafe).status == "fail"
    assert grain_axis_result(safe).status == "pass"
    assert grain_axis_result(unknown).status == "unknown"
    evidence = grain_axis_result(unsafe).evidence
    assert evidence["grain_status"] == "unsafe"
    assert evidence["fan_out_paths"], "fail evidence must carry the join path"


def test_empirical_inflation_corroborates_static_verdict() -> None:
    """The $100 order x 3 shipments worked example, executed for real."""
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE orders (order_id INTEGER, amount DOUBLE)")
    con.execute("INSERT INTO orders VALUES (1, 100.0), (2, 50.0)")
    con.execute("CREATE TABLE shipments (shipment_id INTEGER, order_id INTEGER)")
    con.execute("INSERT INTO shipments VALUES (10, 1), (11, 1), (12, 1), (13, 2)")

    sql = "SELECT sum(o.amount) FROM orders o JOIN shipments s ON o.order_id = s.order_id"
    check = empirical_inflation(con, sql, fan_table="shipments", key_columns=["order_id"])

    assert check.original == 350.0  # 100*3 + 50*1
    assert check.deduplicated == 150.0  # the true total
    assert check.inflation == pytest.approx(350.0 / 150.0)
