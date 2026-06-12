"""Orchestrate runs: seeds, repetitions, retries, traces, manifest.

The executor drives one adapter over an item list under the safety and budget
rails, streaming a deterministic trace per attempt and emitting a RunManifest
at the end. It knows nothing about scoring -- traces are the only interface
between execution and judgment, which is what makes re-scoring old runs
possible without calling any model again.

Retries are transport-only (an :class:`~ledgerbench.errors.AdapterError`),
with exponential backoff; a *wrong answer* is never retried, it is recorded
and later scored. A budget abort finalizes a valid partial manifest -- traces
already written stay usable.
"""

from __future__ import annotations

import datetime
import decimal
import json
import logging
import statistics
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import duckdb

import ledgerbench
from ledgerbench.adapters.base import AgentAdapter
from ledgerbench.contracts.agent_io import (
    AgentRequest,
    AgentResponse,
    Budget,
    MalformedResponse,
    parse_agent_response,
)
from ledgerbench.contracts.item import Item
from ledgerbench.contracts.manifest import RunManifest, RunTotals
from ledgerbench.errors import (
    AdapterError,
    BudgetExceededError,
    CallBudgetExceededError,
    SQLSafetyError,
)
from ledgerbench.runner.budget import BudgetTracker
from ledgerbench.runner.safety import SafeExecutor
from ledgerbench.runner.trace import SqlExecution, TraceRecord, TraceWriter

logger = logging.getLogger(__name__)

_RETRY_BACKOFF_S = (0.5, 2.0)  # transport retries: attempt n sleeps backoff[n]


@dataclass(frozen=True)
class RunSpec:
    """Everything one run needs beyond the items and the adapter."""

    db_paths: Mapping[str, Path]
    schema_ddls: Mapping[str, str]
    context_packs: Mapping[str, str]
    condition: Literal["closed", "open"]
    seeds: tuple[int, ...]
    trace_path: Path
    suite_version: str
    suite_hash: str
    world_hashes: Mapping[str, str]
    timeout_s: float = 30.0
    row_cap: int = 100_000
    max_transport_retries: int = 2


def load_items(path: str | Path) -> list[Item]:
    """Load and validate an item list from JSONL."""
    items = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                items.append(Item.model_validate_json(line))
    return items


def git_commit() -> str:
    """Current commit SHA for the manifest; 'unknown' outside a repo."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


class _GatedSql:
    """The execution callback handed to adapters: gated, counted, recorded."""

    def __init__(self, executor: SafeExecutor, budget: BudgetTracker, item_id: str) -> None:
        self._executor = executor
        self._budget = budget
        self._item_id = item_id
        self.calls: list[str] = []

    def __call__(self, sql: str) -> list[tuple[object, ...]]:
        self._budget.count_call(self._item_id)
        rows = self._executor.execute(sql)
        self.calls.append(self._executor.audit_log[-1])
        return rows


def _call_with_retries(
    adapter: AgentAdapter,
    request: AgentRequest,
    gated: _GatedSql,
    max_retries: int,
) -> object:
    """Transport-only retries with bounded exponential backoff."""
    last: AdapterError | None = None
    for attempt in range(max_retries + 1):
        try:
            return adapter.complete(request, gated)
        except AdapterError as exc:
            last = exc
            logger.warning("adapter transport failure attempt=%d err=%s", attempt, exc)
            if attempt < max_retries:
                time.sleep(_RETRY_BACKOFF_S[min(attempt, len(_RETRY_BACKOFF_S) - 1)])
    assert last is not None
    raise last


def _verify_sql(response: AgentResponse | None, safe: SafeExecutor) -> SqlExecution:
    """Independently execute the answer SQL through the gate for the trace."""
    if response is None or not response.sql:
        return SqlExecution(status="skipped")
    try:
        rows = safe.execute(response.sql)
    except SQLSafetyError as exc:
        return SqlExecution(status="blocked", error=str(exc))
    except Exception as exc:
        return SqlExecution(status="error", error=str(exc)[:300])
    value: float | None = None
    if rows and rows[0] and isinstance(rows[0][0], int | float | decimal.Decimal):
        value = float(rows[0][0])
    return SqlExecution(
        status="ok",
        vetted_sql=safe.audit_log[-1],
        value=value,
        row_count=len(rows),
    )


def run_items(
    items: Sequence[Item],
    adapter: AgentAdapter,
    spec: RunSpec,
    budget: BudgetTracker,
) -> RunManifest:
    """Run every item x seed, streaming traces; return the manifest.

    A :class:`BudgetExceededError` aborts remaining work but still returns a
    valid partial manifest covering everything already traced.
    """
    connections: dict[str, duckdb.DuckDBPyConnection] = {}
    safes: dict[str, SafeExecutor] = {}
    for world, db_path in spec.db_paths.items():
        con = duckdb.connect(str(db_path), read_only=True)
        connections[world] = con
        safes[world] = SafeExecutor(con, timeout_s=spec.timeout_s, row_cap=spec.row_cap)

    latencies_ms: list[float] = []
    completed = 0
    aborted = False
    try:
        with TraceWriter(spec.trace_path) as writer:
            for repetition, seed in enumerate(spec.seeds):
                if aborted:
                    break
                for item in items:
                    safe = safes[item.world]
                    request = AgentRequest(
                        item_id=item.id,
                        question=item.question,
                        schema_ddl=spec.schema_ddls[item.world],
                        context_pack=(
                            spec.context_packs.get(item.world) if spec.condition == "open" else None
                        ),
                        budget=Budget(
                            max_calls=budget.max_calls_per_item, timeout_s=spec.timeout_s
                        ),
                    )
                    budget.start_item(item.id)
                    gated = _GatedSql(safe, budget, item.id)

                    started = time.perf_counter()
                    try:
                        raw = _call_with_retries(
                            adapter, request, gated, spec.max_transport_retries
                        )
                        budget.add_cost(float(getattr(adapter, "last_cost_usd", 0.0)))
                    except CallBudgetExceededError as exc:
                        # Scoped to this item: record the failure, keep running.
                        raw = json.dumps({"budget_error": str(exc)})
                    except BudgetExceededError:
                        logger.warning("budget abort at item=%s seed=%d", item.id, seed)
                        aborted = True
                        break
                    except AdapterError as exc:
                        raw = json.dumps({"transport_error": str(exc)})
                    latencies_ms.append((time.perf_counter() - started) * 1000)

                    parsed = parse_agent_response(raw)
                    response = parsed if isinstance(parsed, AgentResponse) else None
                    malformed = parsed if isinstance(parsed, MalformedResponse) else None

                    writer.write(
                        TraceRecord(
                            item_id=item.id,
                            seed=seed,
                            repetition=repetition,
                            condition=spec.condition,
                            request=request,
                            raw_payload=_jsonable(raw),
                            response=response,
                            malformed=malformed,
                            execution=_verify_sql(response, safe),
                            adapter_sql_calls=tuple(gated.calls),
                        )
                    )
                    completed += 1
    finally:
        for con in connections.values():
            con.close()

    if latencies_ms:
        ordered = sorted(latencies_ms)
        p50 = statistics.median(ordered)
        p95 = ordered[min(len(ordered) - 1, round(0.95 * len(ordered)) - 1)]
    else:
        p50 = p95 = 0.0

    return RunManifest(
        tool_version=ledgerbench.__version__,
        suite_version=spec.suite_version,
        suite_hash=spec.suite_hash,
        world_hashes=dict(spec.world_hashes),
        agent_id=adapter.name,
        model_snapshot_id=getattr(adapter, "model", None),
        condition=spec.condition,
        seeds=spec.seeds,
        repetitions=len(spec.seeds),
        totals=RunTotals(
            items=completed,
            cost_usd=round(budget.spent_usd, 6),
            latency_p50_ms=round(p50, 3),
            latency_p95_ms=round(p95, 3),
        ),
        git_commit=git_commit(),
        created_at=datetime.datetime.now(datetime.UTC),
    )


def _jsonable(raw: object) -> object:
    """Coerce an arbitrary adapter payload into something JSON-serializable."""
    if isinstance(raw, str | int | float | bool | dict | list) or raw is None:
        return raw
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return repr(raw)
