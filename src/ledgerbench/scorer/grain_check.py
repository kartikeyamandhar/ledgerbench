"""Axis 2 (grain safety): static fan-out analysis of agent SQL.

Decides -- without executing anything -- whether a query inflates an aggregate
through a join that multiplies rows (fan trap, chasm trap, or a dimension
measure summed across a fact join). The verdict is one of ``safe``, ``unsafe``
(with the offending join path), ``needs_distinct`` (a COUNT that is fixable by
DISTINCT), or ``unknown``.

The rule is **fail closed**: anything outside the supported-constructs fence
returns ``unknown``, never a guess. Supported: a single SELECT; INNER/LEFT
equi-joins; GROUP BY / HAVING; SUM, AVG, COUNT, MIN, MAX; CTEs and derived
tables one level deep; WHERE subqueries one level deep; pre-aggregation
repairs (the many side grouped or DISTINCT-ed to the join key before joining).

Fan-out model: each equi-join edge between two sources is oriented one->many
from declared :class:`~ledgerbench.registry.grain_model.GrainModel`
cardinalities (or inferred for pre-aggregated derived tables, which are unique
per their group keys). For tree-shaped join graphs, a source's rows are
duplicated in the result exactly when a breadth-first walk from that source
traverses an edge in the one->many direction moving *away* from it. Summing or
averaging a duplicated source's column is ``unsafe``; counting one is
``needs_distinct``; MIN/MAX are duplicate-insensitive; ``COUNT(*)`` is unsafe
only when *no* source is duplicate-free (the result grain matches no declared
table, the chasm shape). Cyclic join graphs are out of fence (``unknown``).

This module is deliberately generic -- SQL + GrainModel in, verdict out; it
imports nothing from the runner and never executes input (see ADR-0004).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import TYPE_CHECKING, Literal

import sqlglot
from pydantic import BaseModel, ConfigDict, Field
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError
from sqlglot.optimizer.scope import Scope, build_scope

from ledgerbench.contracts.verdict import AxisResult
from ledgerbench.registry.grain_model import GrainModel

if TYPE_CHECKING:
    import duckdb

GrainStatus = Literal["safe", "unsafe", "needs_distinct", "unknown"]

_ALLOWED_AGGS = (exp.Sum, exp.Avg, exp.Count, exp.Min, exp.Max)

_DENIED_NODES: tuple[tuple[type[exp.Expression], str], ...] = (
    (exp.Window, "window function"),
    (exp.Union, "UNION"),
    (exp.Intersect, "INTERSECT"),
    (exp.Except, "EXCEPT"),
    (exp.Lateral, "LATERAL"),
    (exp.Unnest, "UNNEST"),
    (exp.Pivot, "PIVOT/UNPIVOT"),
    (exp.Qualify, "QUALIFY clause"),
)


class FanOutEdge(BaseModel):
    """One join edge that multiplies rows; evidence for the report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    from_table: str
    to_table: str
    cardinality: str


class GrainCheckResult(BaseModel):
    """The grain-safety verdict for one query, with self-explaining evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: GrainStatus
    fan_out_paths: tuple[FanOutEdge, ...] = ()
    offending_aggregates: tuple[str, ...] = ()
    unsupported: str | None = None
    notes: tuple[str, ...] = ()


class EmpiricalCheck(BaseModel):
    """Secondary, execution-based corroboration of a static verdict."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    original: float
    deduplicated: float
    inflation: float | None = Field(default=None, ge=0.0)


def _unknown(reason: str) -> GrainCheckResult:
    return GrainCheckResult(status="unknown", unsupported=reason)


class _Fence(Exception):
    """Internal: a construct outside the supported fence was encountered."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass
class _Source:
    """A scope-level join source, normalized for cardinality reasoning."""

    alias: str
    kind: Literal["table", "passthrough", "keyed", "projected", "singleton", "opaque"]
    table: str | None = None
    keys: frozenset[str] = frozenset()
    fanned_columns: frozenset[str] = frozenset()
    child_edges: tuple[FanOutEdge, ...] = ()


@dataclass
class _Edge:
    """An equi-join edge; ``many_alias`` is the side whose rows multiply."""

    a: str
    b: str
    many_alias: str | None  # None = 1:1; "*" = both sides (many_to_many)
    display: FanOutEdge | None


@dataclass
class _Findings:
    """Accumulated verdict inputs across all scopes."""

    unsafe_paths: list[FanOutEdge] = dc_field(default_factory=list)
    unsafe_aggs: list[str] = dc_field(default_factory=list)
    needs_distinct_aggs: list[str] = dc_field(default_factory=list)
    unknown_reasons: list[str] = dc_field(default_factory=list)
    notes: list[str] = dc_field(default_factory=list)


def _flatten_conjunction(node: exp.Expression) -> Iterator[exp.Expression]:
    if isinstance(node, exp.And):
        yield from _flatten_conjunction(node.this)
        yield from _flatten_conjunction(node.expression)
    else:
        yield node


def _output_columns(select: exp.Select) -> dict[str, exp.Expression] | None:
    """Map output column names to defining expressions; None if unmappable."""
    out: dict[str, exp.Expression] = {}
    for item in select.selects:
        if isinstance(item, exp.Alias):
            out[item.alias] = item.this
        elif isinstance(item, exp.Column):
            out[item.name] = item
        else:
            return None
    return out


def _classify_child(scope: Scope, grain_model: GrainModel) -> _Source:
    """Normalize a one-level CTE/derived-table scope into a join source."""
    select = scope.expression
    if not isinstance(select, exp.Select):
        return _Source(alias="", kind="opaque")

    outputs = _output_columns(select)
    aggs = list(scope.find_all(*_ALLOWED_AGGS))
    group = select.args.get("group")
    distinct = select.args.get("distinct") is not None
    joins = select.args.get("joins") or []

    if group is not None:
        if outputs is None:
            return _Source(alias="", kind="opaque")
        key_names: set[str] = set()
        for g in group.expressions:
            if not isinstance(g, exp.Column):
                return _Source(alias="", kind="opaque")
            for name, expr in outputs.items():
                if isinstance(expr, exp.Column) and expr.name == g.name and expr.table == g.table:
                    key_names.add(name)
        # Grouped output is unique per its key tuple regardless of internals.
        return _Source(alias="", kind="keyed", keys=frozenset(key_names))

    if distinct:
        if outputs is None:
            return _Source(alias="", kind="opaque")
        return _Source(alias="", kind="keyed", keys=frozenset(outputs))

    if aggs:
        return _Source(alias="", kind="singleton")

    if not joins:
        tables = [s for s in scope.sources.values() if isinstance(s, exp.Table)]
        if len(tables) == 1 and len(scope.sources) == 1:
            return _Source(alias="", kind="passthrough", table=tables[0].name)
        return _Source(alias="", kind="opaque")

    # Non-aggregating child with joins: its projections carry the child's own
    # fan-out. Analyze it internally so the parent can flag sums over them.
    if outputs is None:
        return _Source(alias="", kind="opaque")
    try:
        child_sources = _scope_sources(scope, grain_model, allow_child_scopes=False)
        edges = _scope_edges(scope, child_sources, grain_model)
        fanned = _fanned_aliases(child_sources, edges)
    except _Fence:
        return _Source(alias="", kind="opaque")
    fanned_cols: set[str] = set()
    for name, expr in outputs.items():
        refs = [expr] if isinstance(expr, exp.Column) else list(expr.find_all(exp.Column))
        for col in refs:
            alias = col.table or next(iter(child_sources))
            if alias in fanned:
                fanned_cols.add(name)
    child_edges = tuple(edge for evidence in fanned.values() for edge in evidence)
    return _Source(
        alias="",
        kind="projected",
        fanned_columns=frozenset(fanned_cols),
        child_edges=tuple(dict.fromkeys(child_edges)),
    )


def _scope_sources(
    scope: Scope, grain_model: GrainModel, *, allow_child_scopes: bool
) -> dict[str, _Source]:
    sources: dict[str, _Source] = {}
    for alias, src in scope.sources.items():
        if isinstance(src, exp.Table):
            sources[alias] = _Source(alias=alias, kind="table", table=src.name)
        elif isinstance(src, Scope) and allow_child_scopes:
            child = _classify_child(src, grain_model)
            child.alias = alias
            sources[alias] = child
        else:
            raise _Fence("nesting deeper than one level")
    return sources


def _join_unique_on(source: _Source, columns: Sequence[str], grain_model: GrainModel) -> bool:
    """Whether ``source`` has at most one row per value of ``columns``."""
    if source.kind in ("table", "passthrough"):
        assert source.table is not None  # set for these kinds by construction
        table = grain_model.tables.get(source.table)
        if table is None:
            raise _Fence(f"table {source.table!r} not in grain model")
        return set(table.primary_key) <= set(columns)
    if source.kind == "keyed":
        if not set(columns) <= source.keys:
            raise _Fence("join on a non-key column of a pre-aggregated derived table")
        return True
    if source.kind == "singleton":
        return True
    raise _Fence("derived table with internal joins used as a join source")


def _display_name(source: _Source) -> str:
    if source.table is not None:
        return source.table
    return f"derived:{source.alias}"


def _scope_edges(scope: Scope, sources: dict[str, _Source], grain_model: GrainModel) -> list[_Edge]:
    select = scope.expression
    assert isinstance(select, exp.Select)  # guarded by check_grain / classification
    joins = select.args.get("joins") or []
    pair_cols: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)

    for join in joins:
        side, kind = join.side or "", join.kind or ""
        if side in ("RIGHT", "FULL"):
            raise _Fence(f"{side} join")
        if kind in ("CROSS", "SEMI", "ANTI"):
            raise _Fence(f"{kind} join")
        if join.args.get("using"):
            raise _Fence("USING join")
        on = join.args.get("on")
        if on is None:
            raise _Fence("join without an ON condition")
        for predicate in _flatten_conjunction(on):
            if not isinstance(predicate, exp.EQ):
                raise _Fence("non-equi join condition")
            left, right = predicate.this, predicate.expression
            if not isinstance(left, exp.Column) or not isinstance(right, exp.Column):
                raise _Fence("non-column join condition")
            if not left.table or not right.table:
                raise _Fence("unqualified column in a join condition")
            if left.table == right.table:
                raise _Fence("join condition within a single source")
            if left.table > right.table:
                left, right = right, left
            pair_cols[(left.table, right.table)].append((left.name, right.name))

    edges: list[_Edge] = []
    for (alias_a, alias_b), colpairs in pair_cols.items():
        src_a, src_b = sources.get(alias_a), sources.get(alias_b)
        if src_a is None or src_b is None:
            raise _Fence("join references an unknown source alias")
        cols_a = [pair[0] for pair in colpairs]
        cols_b = [pair[1] for pair in colpairs]

        if src_a.kind in ("table", "passthrough") and src_b.kind in ("table", "passthrough"):
            assert src_a.table is not None and src_b.table is not None
            for tbl in (src_a.table, src_b.table):
                if tbl not in grain_model.tables:
                    raise _Fence(f"table {tbl!r} not in grain model")
            card = grain_model.cardinality(src_a.table, src_b.table)
            if card is None:
                raise _Fence(
                    f"no declared relationship between {src_a.table!r} and {src_b.table!r}"
                )
            # Evidence is always displayed in the one -> many direction.
            many: str | None
            if card == "one_to_many":
                many = alias_b
                one_table, many_table = src_a.table, src_b.table
            elif card == "many_to_one":
                many = alias_a
                one_table, many_table = src_b.table, src_a.table
            elif card == "many_to_many":
                many = "*"
                one_table, many_table = src_a.table, src_b.table
            else:
                many = None
                one_table, many_table = src_a.table, src_b.table
            shown_card = "one_to_many" if card in ("one_to_many", "many_to_one") else card
            display = (
                FanOutEdge(from_table=one_table, to_table=many_table, cardinality=shown_card)
                if many is not None
                else None
            )
            edges.append(_Edge(a=alias_a, b=alias_b, many_alias=many, display=display))
            continue

        unique_a = _join_unique_on(src_a, cols_a, grain_model)
        unique_b = _join_unique_on(src_b, cols_b, grain_model)
        if unique_a and unique_b:
            edges.append(_Edge(a=alias_a, b=alias_b, many_alias=None, display=None))
        else:
            many_alias = alias_b if unique_a else alias_a
            one_src, many_src = (src_a, src_b) if unique_a else (src_b, src_a)
            edges.append(
                _Edge(
                    a=alias_a,
                    b=alias_b,
                    many_alias=many_alias,
                    display=FanOutEdge(
                        from_table=_display_name(one_src),
                        to_table=_display_name(many_src),
                        cardinality="one_to_many (inferred)",
                    ),
                )
            )
    return edges


def _fanned_aliases(
    sources: dict[str, _Source], edges: list[_Edge]
) -> dict[str, tuple[FanOutEdge, ...]]:
    """BFS the join tree from each source; collect the edges that multiply it.

    A source's rows are duplicated exactly when a walk away from it crosses an
    edge in the one->many direction. Cyclic join graphs are out of fence.
    """
    adjacency: dict[str, list[tuple[str, _Edge]]] = defaultdict(list)
    nodes: set[str] = set()
    for edge in edges:
        adjacency[edge.a].append((edge.b, edge))
        adjacency[edge.b].append((edge.a, edge))
        nodes.update((edge.a, edge.b))

    # Tree check: in a forest, |edges| == |nodes| - |components|.
    seen: set[str] = set()
    components = 0
    for node in nodes:
        if node in seen:
            continue
        components += 1
        stack = [node]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(n for n, _ in adjacency[current] if n not in seen)
    if len(edges) > len(nodes) - components:
        raise _Fence("cyclic join graph")

    fanned: dict[str, tuple[FanOutEdge, ...]] = {}
    for start in sources:
        if start not in nodes:
            continue
        evidence: list[FanOutEdge] = []
        visited = {start}
        queue = [start]
        while queue:
            current = queue.pop(0)
            for neighbor, edge in adjacency[current]:
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                queue.append(neighbor)
                if edge.many_alias in (neighbor, "*") and edge.display is not None:
                    evidence.append(edge.display)
        if evidence:
            fanned[start] = tuple(dict.fromkeys(evidence))
    return fanned


def _resolve_column_alias(col: exp.Column, sources: dict[str, _Source]) -> str:
    if col.table:
        if col.table not in sources:
            raise _Fence(f"column references unknown source {col.table!r}")
        return col.table
    if len(sources) == 1:
        return next(iter(sources))
    raise _Fence("unqualified column in a multi-source query")


def _analyze_scope(scope: Scope, grain_model: GrainModel, findings: _Findings) -> None:
    is_root = scope.parent is None
    sources = _scope_sources(scope, grain_model, allow_child_scopes=is_root)
    edges = _scope_edges(scope, sources, grain_model)
    fanned = _fanned_aliases(sources, edges)

    for agg in scope.find_all(exp.AggFunc):
        if not isinstance(agg, _ALLOWED_AGGS):
            raise _Fence(f"unsupported aggregate {type(agg).__name__.upper()}")
        if isinstance(agg, exp.Min | exp.Max):
            continue  # duplicate-insensitive
        distinct = agg.find(exp.Distinct) is not None
        columns = list(agg.find_all(exp.Column))

        if isinstance(agg, exp.Count):
            if distinct:
                continue
            if not columns:  # COUNT(*) / COUNT(1): counts result rows
                joined = {alias for e in edges for alias in (e.a, e.b)}
                if joined and all(alias in fanned for alias in joined):
                    findings.unsafe_aggs.append(agg.sql(dialect="duckdb"))
                    for evidence in fanned.values():
                        findings.unsafe_paths.extend(evidence)
                    findings.notes.append(
                        "COUNT over a join whose result grain matches no declared table"
                    )
                continue
        elif distinct:
            raise _Fence("DISTINCT inside SUM/AVG")

        offending: list[FanOutEdge] = []
        for col in columns:
            alias = _resolve_column_alias(col, sources)
            source = sources[alias]
            if source.kind == "projected" and col.name in source.fanned_columns:
                offending.extend(source.child_edges)
            if alias in fanned:
                offending.extend(fanned[alias])
        if offending:
            if isinstance(agg, exp.Count):
                findings.needs_distinct_aggs.append(agg.sql(dialect="duckdb"))
            else:
                findings.unsafe_aggs.append(agg.sql(dialect="duckdb"))
            findings.unsafe_paths.extend(offending)


def check_grain(sql: str, grain_model: GrainModel, *, dialect: str = "duckdb") -> GrainCheckResult:
    """Statically decide whether ``sql`` inflates an aggregate through a join.

    Args:
        sql: The query to analyze. Never executed.
        grain_model: Declared table grains and relationship cardinalities.
        dialect: sqlglot dialect to parse with (duckdb in v1).

    Returns:
        A :class:`GrainCheckResult`; ``unknown`` whenever the query leaves the
        documented supported-constructs fence (fail closed, never a guess).
    """
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except (ParseError, TokenError, ValueError):
        return _unknown("SQL could not be parsed")
    if not isinstance(tree, exp.Select):
        return _unknown(f"not a single SELECT statement ({type(tree).__name__})")
    for node_type, reason in _DENIED_NODES:
        if tree.find(node_type) is not None:
            return _unknown(reason)

    root = build_scope(tree)
    if root is None:
        return _unknown("could not resolve query scopes")

    child_scopes = [*root.cte_scopes, *root.derived_table_scopes, *root.subquery_scopes]
    for child in child_scopes:
        if child.cte_scopes or child.derived_table_scopes or child.subquery_scopes:
            return _unknown("nesting deeper than one level")

    findings = _Findings()
    try:
        for scope in (root, *child_scopes):
            _analyze_scope(scope, grain_model, findings)
    except _Fence as fence:
        findings.unknown_reasons.append(fence.reason)

    if findings.unsafe_aggs:
        return GrainCheckResult(
            status="unsafe",
            fan_out_paths=tuple(dict.fromkeys(findings.unsafe_paths)),
            offending_aggregates=tuple(dict.fromkeys(findings.unsafe_aggs)),
            notes=tuple(findings.notes),
        )
    if findings.needs_distinct_aggs:
        return GrainCheckResult(
            status="needs_distinct",
            fan_out_paths=tuple(dict.fromkeys(findings.unsafe_paths)),
            offending_aggregates=tuple(dict.fromkeys(findings.needs_distinct_aggs)),
            notes=tuple(findings.notes),
        )
    if findings.unknown_reasons:
        return _unknown(findings.unknown_reasons[0])
    return GrainCheckResult(status="safe", notes=tuple(findings.notes))


def grain_axis_result(result: GrainCheckResult) -> AxisResult:
    """Map a grain verdict onto the scorer's axis vocabulary."""
    status_map: dict[GrainStatus, Literal["pass", "fail", "unknown"]] = {
        "safe": "pass",
        "unsafe": "fail",
        "needs_distinct": "fail",
        "unknown": "unknown",
    }
    return AxisResult(
        status=status_map[result.status],
        evidence={
            "grain_status": result.status,
            "fan_out_paths": [
                f"{e.from_table} -> {e.to_table} ({e.cardinality})" for e in result.fan_out_paths
            ],
            "offending_aggregates": list(result.offending_aggregates),
            "unsupported": result.unsupported,
        },
    )


def empirical_inflation(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    *,
    fan_table: str,
    key_columns: Sequence[str],
    dialect: str = "duckdb",
) -> EmpiricalCheck:
    """Corroborate a static verdict by re-running with the fan side deduped.

    Replaces every reference to ``fan_table`` with
    ``SELECT DISTINCT key_columns FROM fan_table`` and compares the two scalar
    results. Secondary evidence only (ADR-0004): it requires execution and a
    dataset, which the primary static path must not.

    Args:
        con: An open DuckDB connection (read-only is fine).
        sql: A query returning a single scalar.
        fan_table: The many-side table to deduplicate.
        key_columns: The join key columns to keep in the deduplicated side.
        dialect: SQL dialect for parse/render.

    Returns:
        Original value, deduplicated value, and their ratio (None when the
        deduplicated value is zero).
    """
    cols = ", ".join(key_columns)
    dedup = sqlglot.parse_one(f"SELECT DISTINCT {cols} FROM {fan_table}", read=dialect)

    def replace(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.Table) and node.name == fan_table:
            return exp.Subquery(this=dedup.copy(), alias=node.alias_or_name)
        return node

    deduped_sql = sqlglot.parse_one(sql, read=dialect).transform(replace).sql(dialect=dialect)
    original_row = con.execute(sql).fetchone()
    deduped_row = con.execute(deduped_sql).fetchone()
    if original_row is None or deduped_row is None:
        raise ValueError("empirical check queries must return one scalar row")
    original = float(original_row[0])
    deduplicated = float(deduped_row[0])
    inflation = original / deduplicated if deduplicated else None
    return EmpiricalCheck(original=original, deduplicated=deduplicated, inflation=inflation)
