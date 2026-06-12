"""Compile a metric definition (plus recipe params) to SQL and execute it for gold.

Ground truth by construction: gold is *derived*, never judged. The SQL shape is
mechanical -- ``SELECT <measure> FROM <base_table>`` with the definition's
filters included, its exclusions negated, and the recipe's ``extra_where``
predicates appended. The ``reference_date`` token that rulebook filters may use
is substituted with the world's declared reference date. No model is ever
involved, and the compiled query passes the same SELECT-only safety gate as
agent SQL before executing (defense in depth applies to our own queries too).

The params vocabulary is deliberately tiny in v1: ``extra_where`` only. This is
the same compiler BYO mode points at a user warehouse in Phase 7.
"""

from __future__ import annotations

import datetime
import re
from typing import TYPE_CHECKING

from pydantic import JsonValue

from ledgerbench.contracts.item import GoldRecipe
from ledgerbench.errors import LedgerBenchError
from ledgerbench.registry.definitions import MetricDefinition
from ledgerbench.runner.safety import vet_sql

if TYPE_CHECKING:
    import duckdb

_REFERENCE_DATE_TOKEN = re.compile(r"\breference_date\b")


def _substitute_reference_date(predicate: str, reference_date: datetime.date) -> str:
    return _REFERENCE_DATE_TOKEN.sub(f"DATE '{reference_date.isoformat()}'", predicate)


def _extra_where(params: dict[str, JsonValue]) -> list[str]:
    """Validate and extract the (only) supported recipe parameter."""
    unknown = set(params) - {"extra_where"}
    if unknown:
        raise LedgerBenchError(f"unsupported gold recipe params: {sorted(unknown)}")
    raw = params.get("extra_where", [])
    if not isinstance(raw, list) or not all(isinstance(p, str) and p.strip() for p in raw):
        raise LedgerBenchError("extra_where must be a list of non-empty predicate strings")
    return [str(p) for p in raw]


def compile_recipe(
    definition: MetricDefinition,
    recipe: GoldRecipe,
    *,
    reference_date: datetime.date,
) -> str:
    """Render the gold SQL for one metric + recipe; vetted before returning.

    Raises:
        LedgerBenchError: unknown params, or the compiled SQL fails the gate
            (which would indicate a corrupt rulebook or item, not agent input).
    """
    if recipe.metric_id != definition.id:
        raise LedgerBenchError(
            f"recipe metric {recipe.metric_id!r} does not match definition {definition.id!r}"
        )

    predicates = [_substitute_reference_date(f, reference_date) for f in definition.filters]
    predicates += [
        f"NOT ({_substitute_reference_date(x, reference_date)})" for x in definition.exclusions
    ]
    predicates += _extra_where(dict(recipe.params))

    sql = f"SELECT {definition.measure} FROM {definition.base_table}"
    if predicates:
        sql += " WHERE " + " AND ".join(f"({p})" for p in predicates)
    return vet_sql(sql)


def compute_gold(
    con: duckdb.DuckDBPyConnection,
    definition: MetricDefinition,
    recipe: GoldRecipe,
    *,
    reference_date: datetime.date,
) -> float:
    """Compile and execute one recipe; return the scalar gold value.

    Raises:
        LedgerBenchError: the query returned no scalar (e.g. an empty window
            summing to NULL) or a non-numeric value -- a defective item, never
            a score.
    """
    sql = compile_recipe(definition, recipe, reference_date=reference_date)
    row = con.execute(sql).fetchone()
    value = row[0] if row else None
    if value is None:
        raise LedgerBenchError(
            f"gold for {definition.id!r} computed NULL (empty window?); sql: {sql}"
        )
    try:
        gold = float(value)
    except (TypeError, ValueError) as exc:
        raise LedgerBenchError(f"gold for {definition.id!r} is non-numeric: {value!r}") from exc
    if definition.value_type == "count" and gold != int(gold):
        raise LedgerBenchError(f"count gold for {definition.id!r} is fractional: {gold}")
    return gold


def connect_warehouse(url: str) -> duckdb.DuckDBPyConnection:
    """Open a read-only connection to the user's warehouse from a URL.

    v1 supports ``duckdb:///absolute/path.duckdb`` (and a bare filesystem
    path). The adapter seam for other warehouses is this function's signature;
    Snowflake lands post-launch (RT-001).

    Raises:
        LedgerBenchError: unsupported scheme or unreadable database, with the
            supported form spelled out.
    """
    import duckdb as _duckdb

    if url.startswith("duckdb://"):
        path = url.removeprefix("duckdb://").lstrip("/")
        path = f"/{path}" if not path.startswith("/") else path
    elif "://" in url:
        scheme = url.split("://", 1)[0]
        raise LedgerBenchError(
            f"unsupported warehouse scheme {scheme!r}; v1 supports "
            f"duckdb:////absolute/path.duckdb (Snowflake is post-launch)"
        )
    else:
        path = url
    try:
        return _duckdb.connect(path, read_only=True)
    except Exception as exc:
        raise LedgerBenchError(f"cannot open warehouse {path!r} read-only: {exc}") from exc
