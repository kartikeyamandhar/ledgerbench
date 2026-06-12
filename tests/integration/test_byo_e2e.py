"""BYO end to end: parse -> generate -> review -> run (naive) -> score -> report."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

from ledgerbench.cli import app
from ledgerbench.generator.suite import generate_suite, load_bank, suite_hash
from ledgerbench.ingestion.dbt_manifest import load_dbt_manifest

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "tiny_dbt_project"
runner = CliRunner()


@pytest.fixture(scope="module")
def warehouse(tmp_path_factory) -> Path:
    spec = importlib.util.spec_from_file_location("build_wh", FIXTURE / "build_warehouse.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_wh"] = module
    spec.loader.exec_module(module)
    return module.build(tmp_path_factory.mktemp("byo") / "tiny.duckdb")


def _schema_ddl(con: duckdb.DuckDBPyConnection) -> str:
    rows = con.execute("SELECT sql FROM duckdb_tables() WHERE internal = false").fetchall()
    return "\n".join(f"{row[0]};" for row in rows)


def test_generate_produces_at_least_20_computable_traps(warehouse) -> None:
    sem = load_dbt_manifest(FIXTURE / "manifest.json")
    con = duckdb.connect(str(warehouse), read_only=True)
    try:
        items, coverage = generate_suite(sem, con)
    finally:
        con.close()
    assert len(items) >= 20
    answer_items = [i for i in items if i.expected_action == "answer"]
    assert len(answer_items) >= 20  # gold recomputed for each inside generate_suite
    assert not coverage.skipped, coverage.skipped
    assert all("Generated from" in i.rubric or "Control generated" in i.rubric for i in items)


def test_stripped_project_degrades_with_reasons(warehouse) -> None:
    sem = load_dbt_manifest(FIXTURE / "manifest_stripped.json")
    con = duckdb.connect(str(warehouse), read_only=True)
    try:
        items, coverage = generate_suite(sem, con)
    finally:
        con.close()
    assert items == []
    assert set(coverage.skipped) == {
        "definitional",
        "grain",
        "ambiguity",
        "refusal",
        "period",
        "control",
    }
    assert all(reason for reason in coverage.skipped.values())


def test_review_persists_and_is_idempotent(warehouse, tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "generate",
            "--manifest",
            str(FIXTURE / "manifest.json"),
            "--warehouse",
            f"duckdb://{warehouse}",
            "--out",
            str(tmp_path / "gen.jsonl"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "coverage" in result.output

    first = runner.invoke(
        app,
        [
            "review",
            str(tmp_path / "gen.jsonl"),
            "--approve-all",
            "--out",
            str(tmp_path / "a.jsonl"),
        ],
    )
    assert first.exit_code == 0, first.output
    assert (tmp_path / "gen.jsonl.decisions.json").is_file()

    second = runner.invoke(
        app,
        [
            "review",
            str(tmp_path / "gen.jsonl"),
            "--approve-all",
            "--out",
            str(tmp_path / "b.jsonl"),
        ],
    )
    assert second.exit_code == 0
    assert "0 pending" in second.output  # decisions persisted; nothing re-asked
    assert (tmp_path / "a.jsonl").read_bytes() == (tmp_path / "b.jsonl").read_bytes()


def test_full_byo_pipeline_to_report(warehouse, tmp_path) -> None:
    """generate -> approve -> run naive -> score -> render. The product engine."""
    from ledgerbench.adapters.naive import NaiveAdapter
    from ledgerbench.config import DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS
    from ledgerbench.report.html import render_report
    from ledgerbench.runner.budget import BudgetTracker
    from ledgerbench.runner.executor import RunSpec, run_items
    from ledgerbench.runner.trace import read_traces
    from ledgerbench.scorer.pipeline import score_run

    sem = load_dbt_manifest(FIXTURE / "manifest.json")
    con = duckdb.connect(str(warehouse), read_only=True)
    try:
        items, _ = generate_suite(sem, con)
        suite_path = tmp_path / "approved.jsonl"
        with suite_path.open("w", encoding="utf-8") as handle:
            for item in items:
                handle.write(item.model_dump_json(exclude_none=True) + "\n")
        items = load_bank(suite_path)
        world = sem.project_name

        spec = RunSpec(
            db_paths={world: warehouse},
            schema_ddls={world: _schema_ddl(con)},
            context_packs={world: "see dbt project docs"},
            condition="closed",
            seeds=(7,),
            trace_path=tmp_path / "traces.jsonl",
            suite_version="generated_v1",
            suite_hash=suite_hash(suite_path),
            world_hashes={world: "fixture"},
        )
        manifest = run_items(items, NaiveAdapter(), spec, BudgetTracker())
        records = list(read_traces(tmp_path / "traces.jsonl"))
        verdicts = score_run(
            items,
            records,
            registries={world: sem.registry},
            grain_models={world: sem.grain_model},
            connections={world: con},
            reference_dates={world: sem.reference_date},
            judge=None,
        )
        result = render_report(
            items,
            records,
            verdicts,
            manifest,
            registries={world: sem.registry},
            reference_dates={world: sem.reference_date},
            weights=DEFAULT_WEIGHTS,
            thresholds=DEFAULT_THRESHOLDS,
            judge_configured=False,
            out_path=tmp_path / "report.html",
        )
    finally:
        con.close()

    assert manifest.totals.items == len(items)
    assert (tmp_path / "report.html").is_file()
    assert 0.0 <= result.overall <= 1.0
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "tiny_shop" in html  # the BYO project is the world in the report
