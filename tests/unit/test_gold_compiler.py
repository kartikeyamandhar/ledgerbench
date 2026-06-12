"""Gold compiler: mechanical SQL shapes, token substitution, defect detection."""

from __future__ import annotations

import datetime

import duckdb
import pytest

from ledgerbench.contracts.item import GoldRecipe
from ledgerbench.errors import LedgerBenchError
from ledgerbench.gold.compiler import compile_recipe, compute_gold
from ledgerbench.registry.definitions import MetricDefinition

REF = datetime.date(2026, 6, 1)

REVENUE = MetricDefinition(
    id="revenue",
    description="Completed, non-refunded order revenue.",
    base_table="orders",
    measure="sum(amount)",
    value_type="numeric",
    grain=("order_id",),
    filters=("status = 'completed'",),
    exclusions=("refunded = true",),
)

ACTIVE_7D = MetricDefinition(
    id="active_users_7d",
    description="Distinct users active in the trailing 7 days.",
    base_table="events",
    measure="count(distinct user_id)",
    value_type="count",
    grain=("event_id",),
    filters=("event_ts >= reference_date - INTERVAL 7 DAY",),
)


def test_compiled_shape_includes_filters_negated_exclusions_and_params() -> None:
    recipe = GoldRecipe(metric_id="revenue", params={"extra_where": ["amount > 10"]})
    sql = compile_recipe(REVENUE, recipe, reference_date=REF)
    upper = sql.upper()
    assert upper.startswith("SELECT SUM(AMOUNT) FROM ORDERS WHERE")
    assert "STATUS = 'COMPLETED'" in upper
    assert "NOT (REFUNDED = TRUE)" in upper
    assert "AMOUNT > 10" in upper


def test_reference_date_token_is_substituted() -> None:
    sql = compile_recipe(ACTIVE_7D, GoldRecipe(metric_id="active_users_7d"), reference_date=REF)
    assert "reference_date" not in sql.lower()
    assert "2026-06-01" in sql  # the declared date, in whatever form sqlglot renders


def test_unknown_params_are_rejected() -> None:
    recipe = GoldRecipe(metric_id="revenue", params={"surprise": True})
    with pytest.raises(LedgerBenchError, match="unsupported gold recipe params"):
        compile_recipe(REVENUE, recipe, reference_date=REF)


def test_mismatched_metric_id_is_rejected() -> None:
    with pytest.raises(LedgerBenchError, match="does not match"):
        compile_recipe(REVENUE, GoldRecipe(metric_id="other"), reference_date=REF)


def test_compiled_sql_passes_the_safety_gate_by_construction() -> None:
    # compile_recipe vets internally; a malicious extra_where must be refused.
    recipe = GoldRecipe(
        metric_id="revenue",
        params={"extra_where": ["1=1) ; DROP TABLE orders --"]},
    )
    with pytest.raises(LedgerBenchError):
        compile_recipe(REVENUE, recipe, reference_date=REF)


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    connection.execute(
        "CREATE TABLE orders (order_id INTEGER, amount DOUBLE, status VARCHAR, refunded BOOLEAN)"
    )
    connection.execute(
        "INSERT INTO orders VALUES (1, 100.0, 'completed', false), "
        "(2, 50.0, 'completed', true), (3, 25.0, 'pending', false)"
    )
    return connection


def test_compute_gold_applies_definition_mechanically(con) -> None:
    gold = compute_gold(con, REVENUE, GoldRecipe(metric_id="revenue"), reference_date=REF)
    assert gold == 100.0  # refunded and pending rows excluded


def test_null_gold_is_a_defect_not_a_value(con) -> None:
    recipe = GoldRecipe(metric_id="revenue", params={"extra_where": ["amount > 99999"]})
    with pytest.raises(LedgerBenchError, match="NULL"):
        compute_gold(con, REVENUE, recipe, reference_date=REF)
