"""The 10-item offline smoke run: end-to-end executor + naive adapter.

This is what .github/workflows/smoke.yml runs on every PR (no secrets).
Asserts the Phase 4 acceptance criteria: traces + manifest produced, every
record schema-valid, and a same-seed rerun is byte-identical.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ledgerbench.adapters.naive import NaiveAdapter
from ledgerbench.contracts.manifest import RunManifest
from ledgerbench.runner.budget import BudgetTracker
from ledgerbench.runner.executor import RunSpec, load_items, run_items
from ledgerbench.runner.trace import read_traces
from ledgerbench.worlds import WORLDS_DIR, digest_database

ITEMS_PATH = Path(__file__).parent / "items_smoke.jsonl"


def _schema_ddls() -> dict[str, str]:
    return {
        world: (WORLDS_DIR / world / "schema.sql").read_text(encoding="utf-8")
        for world in ("saas", "finance")
    }


def _spec(built_worlds: dict[str, Path], trace_path: Path) -> RunSpec:
    return RunSpec(
        db_paths=built_worlds,
        schema_ddls=_schema_ddls(),
        context_packs={},
        condition="closed",
        seeds=(42,),
        trace_path=trace_path,
        suite_version="smoke_v1",
        suite_hash="smoke",
        world_hashes={w: digest_database(p) for w, p in built_worlds.items()},
    )


@pytest.fixture(scope="module")
def smoke_run(built_worlds, tmp_path_factory) -> tuple[Path, RunManifest]:
    trace_path = tmp_path_factory.mktemp("smoke") / "traces.jsonl"
    manifest = run_items(
        load_items(ITEMS_PATH),
        NaiveAdapter(),
        _spec(built_worlds, trace_path),
        BudgetTracker(),
    )
    return trace_path, manifest


def test_ten_items_yield_ten_traces(smoke_run) -> None:
    trace_path, manifest = smoke_run
    records = list(read_traces(trace_path))
    assert len(records) == 10
    assert manifest.totals.items == 10
    assert manifest.agent_id == "naive"
    assert manifest.totals.cost_usd == 0.0  # offline baseline spends nothing


def test_traces_are_self_contained_evidence(smoke_run) -> None:
    trace_path, _ = smoke_run
    for record in read_traces(trace_path):
        assert record.response is not None, "naive always answers"
        assert record.response.action == "answer"
        assert record.execution.status == "ok", record.execution.error
        assert record.adapter_sql_calls, "the gated callback was used"


def test_manifest_is_schema_valid_roundtrip(smoke_run) -> None:
    _, manifest = smoke_run
    assert RunManifest.model_validate_json(manifest.model_dump_json()) == manifest


def test_same_seed_rerun_is_byte_identical(smoke_run, built_worlds, tmp_path) -> None:
    trace_path, _ = smoke_run
    rerun_path = tmp_path / "rerun.jsonl"
    run_items(
        load_items(ITEMS_PATH),
        NaiveAdapter(),
        _spec(built_worlds, rerun_path),
        BudgetTracker(),
    )
    assert rerun_path.read_bytes() == trace_path.read_bytes()
