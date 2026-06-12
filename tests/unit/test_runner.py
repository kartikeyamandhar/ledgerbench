"""Executor unit tests with a scripted mock adapter: failure paths first."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ledgerbench.adapters.base import AgentAdapter, ExecuteSql, load_adapter
from ledgerbench.contracts.agent_io import AgentRequest
from ledgerbench.contracts.item import Item
from ledgerbench.errors import AdapterError
from ledgerbench.runner.budget import BudgetTracker
from ledgerbench.runner.executor import RunSpec, run_items
from ledgerbench.runner.trace import read_traces

SCHEMA = "CREATE TABLE orders (order_id INTEGER PRIMARY KEY, amount DECIMAL(10,2) NOT NULL);"


@pytest.fixture
def tiny_world(tmp_path) -> Path:
    import duckdb

    db = tmp_path / "tiny.duckdb"
    con = duckdb.connect(str(db))
    con.execute(SCHEMA)
    con.execute("INSERT INTO orders VALUES (1, 100.0), (2, 50.0)")
    con.close()
    return db


def _item(item_id: str = "t-def-001") -> Item:
    return Item(
        id=item_id,
        world="tiny",
        question="What is total order amount?",
        trap_class="definitional",
        expected_action="answer",
        gold_value=150.0,
        rubric="Sum of order amounts.",
        version="test_v1",
    )


def _spec(tiny_world: Path, trace_path: Path, **overrides) -> RunSpec:
    defaults: dict = {
        "db_paths": {"tiny": tiny_world},
        "schema_ddls": {"tiny": SCHEMA},
        "context_packs": {"tiny": "rulebook text"},
        "condition": "closed",
        "seeds": (7,),
        "trace_path": trace_path,
        "suite_version": "test_v1",
        "suite_hash": "t",
        "world_hashes": {"tiny": "deadbeef"},
        "max_transport_retries": 1,
    }
    defaults.update(overrides)
    return RunSpec(**defaults)


class ScriptedAdapter(AgentAdapter):
    """Returns queued payloads; raises queued exceptions; counts calls."""

    name = "scripted"

    def __init__(self, script: list[object]) -> None:
        self.script = list(script)
        self.calls = 0
        self.last_cost_usd = 0.0

    def complete(self, request: AgentRequest, execute_sql: ExecuteSql) -> object:
        self.calls += 1
        action = self.script.pop(0) if self.script else {"action": "refuse"}
        if isinstance(action, Exception):
            raise action
        return action


def test_valid_response_is_traced_and_verified(tiny_world, tmp_path) -> None:
    payload = {"action": "answer", "value": 150.0, "sql": "SELECT sum(amount) FROM orders"}
    manifest = run_items(
        [_item()],
        ScriptedAdapter([payload]),
        _spec(tiny_world, tmp_path / "t.jsonl"),
        BudgetTracker(),
    )
    [record] = list(read_traces(tmp_path / "t.jsonl"))
    assert record.response is not None and record.response.value == 150.0
    assert record.execution.status == "ok" and record.execution.value == 150.0
    assert manifest.totals.items == 1


def test_malformed_payload_is_recorded_not_crashed(tiny_world, tmp_path) -> None:
    run_items(
        [_item()],
        ScriptedAdapter(["not json {{{"]),
        _spec(tiny_world, tmp_path / "t.jsonl"),
        BudgetTracker(),
    )
    [record] = list(read_traces(tmp_path / "t.jsonl"))
    assert record.response is None
    assert record.malformed is not None
    assert record.execution.status == "skipped"


def test_agent_sql_through_gate_blocked_is_evidence(tiny_world, tmp_path) -> None:
    payload = {"action": "answer", "value": 1.0, "sql": "DROP TABLE orders"}
    run_items(
        [_item()],
        ScriptedAdapter([payload]),
        _spec(tiny_world, tmp_path / "t.jsonl"),
        BudgetTracker(),
    )
    [record] = list(read_traces(tmp_path / "t.jsonl"))
    assert record.execution.status == "blocked"
    assert record.execution.error and "denied" in record.execution.error


def test_transport_errors_are_retried_then_recorded(tiny_world, tmp_path) -> None:
    adapter = ScriptedAdapter([AdapterError("boom"), AdapterError("boom again")])
    run_items([_item()], adapter, _spec(tiny_world, tmp_path / "t.jsonl"), BudgetTracker())
    assert adapter.calls == 2  # initial + 1 retry (max_transport_retries=1)
    [record] = list(read_traces(tmp_path / "t.jsonl"))
    assert record.malformed is not None
    assert "transport_error" in json.dumps(record.raw_payload)


def test_transport_retry_then_success(tiny_world, tmp_path) -> None:
    payload = {"action": "answer", "value": 150.0, "sql": "SELECT sum(amount) FROM orders"}
    adapter = ScriptedAdapter([AdapterError("flaky"), payload])
    run_items([_item()], adapter, _spec(tiny_world, tmp_path / "t.jsonl"), BudgetTracker())
    [record] = list(read_traces(tmp_path / "t.jsonl"))
    assert record.response is not None and record.execution.status == "ok"


def test_usd_cap_aborts_with_valid_partial_manifest(tiny_world, tmp_path) -> None:
    class CostlyAdapter(ScriptedAdapter):
        def complete(self, request: AgentRequest, execute_sql: ExecuteSql) -> object:
            self.last_cost_usd = 3.0
            return {"action": "answer", "value": 1.0, "sql": "SELECT 1"}

    items = [_item("t-def-001"), _item("t-def-002"), _item("t-def-003")]
    manifest = run_items(
        items,
        CostlyAdapter([]),
        _spec(tiny_world, tmp_path / "t.jsonl"),
        BudgetTracker(max_usd_per_run=5.0),  # second item crosses the cap
    )
    records = list(read_traces(tmp_path / "t.jsonl"))
    assert len(records) == 1  # aborted before tracing the second
    assert manifest.totals.items == 1
    assert manifest.totals.cost_usd == 6.0  # spend recorded honestly


def test_per_item_call_cap_fails_item_but_run_continues(tiny_world, tmp_path) -> None:
    class GreedyAdapter(ScriptedAdapter):
        def complete(self, request: AgentRequest, execute_sql: ExecuteSql) -> object:
            for _ in range(10):  # blows past max_calls_per_item
                execute_sql("SELECT 1")
            return {"action": "answer", "value": 1.0, "sql": "SELECT 1"}

    items = [_item("t-def-001"), _item("t-def-002")]
    manifest = run_items(
        items, GreedyAdapter([]), _spec(tiny_world, tmp_path / "t.jsonl"), BudgetTracker()
    )
    records = list(read_traces(tmp_path / "t.jsonl"))
    assert len(records) == 2 and manifest.totals.items == 2
    assert all(r.malformed is not None for r in records)
    assert "budget_error" in json.dumps(records[0].raw_payload)


def test_open_condition_includes_context_pack(tiny_world, tmp_path) -> None:
    seen: list[AgentRequest] = []

    class SpyAdapter(ScriptedAdapter):
        def complete(self, request: AgentRequest, execute_sql: ExecuteSql) -> object:
            seen.append(request)
            return {"action": "answer", "value": 1.0, "sql": "SELECT 1"}

    run_items(
        [_item()],
        SpyAdapter([]),
        _spec(tiny_world, tmp_path / "t.jsonl", condition="open"),
        BudgetTracker(),
    )
    assert seen[0].context_pack == "rulebook text"


def test_load_adapter_unknown_name_raises() -> None:
    with pytest.raises(AdapterError, match="unknown adapter"):
        load_adapter("does-not-exist")
