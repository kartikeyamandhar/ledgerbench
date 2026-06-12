"""Roster benchmark runner (staged copy; lands as scripts/run_benchmark.py).

Runs agents x conditions x seeds over the public bank, writing committed-style
results: traces.jsonl + manifest.json + summary.json per (agent, condition).
Resumable: existing result directories with a manifest are skipped.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb

from ledgerbench.adapters.base import load_adapter
from ledgerbench.config import DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS
from ledgerbench.generator.suite import load_bank, suite_hash
from ledgerbench.ingestion.rulebook import load_rulebook
from ledgerbench.report.html import render_report
from ledgerbench.runner.budget import BudgetTracker
from ledgerbench.runner.executor import RunSpec, run_items
from ledgerbench.runner.trace import read_traces
from ledgerbench.scorer.aggregate import aggregate
from ledgerbench.scorer.pipeline import score_run
from ledgerbench.worlds import WORLDS_DIR, build_world, digest_database

SUITE = Path("benchmark/items/public_v1.jsonl")
SEEDS = (11, 22, 33)
WORLD_SEED = 42


def run_roster(agents: list[str], conditions: list[str], out_root: Path) -> None:
    """Run each agent x condition over the public bank; write committed-style results."""
    items = load_bank(SUITE)
    worlds = sorted({i.world for i in items})
    db_paths = {w: build_world(w, seed=WORLD_SEED) for w in worlds}
    schema_ddls = {w: (WORLDS_DIR / w / "schema.sql").read_text(encoding="utf-8") for w in worlds}
    context_packs = {
        w: (WORLDS_DIR / w / "rulebook.yaml").read_text(encoding="utf-8") for w in worlds
    }
    rulebooks = {w: load_rulebook(WORLDS_DIR / w / "rulebook.yaml") for w in worlds}
    registries = {w: rb.to_registry() for w, rb in rulebooks.items()}
    grain_models = {w: rb.to_grain_model() for w, rb in rulebooks.items()}
    reference_dates = {w: rb.reference_date for w, rb in rulebooks.items()}
    world_hashes = {w: digest_database(p) for w, p in db_paths.items()}

    for agent_name in agents:
        for condition in conditions:
            out_dir = out_root / f"{agent_name}-{condition}"
            if (out_dir / "manifest.json").is_file():
                print(f"skip {out_dir} (manifest exists; resume semantics)")
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            print(f"== {agent_name} / {condition} ==")
            spec = RunSpec(
                db_paths=db_paths,
                schema_ddls=schema_ddls,
                context_packs=context_packs,
                condition=condition,  # type: ignore[arg-type]
                seeds=SEEDS,
                trace_path=out_dir / "traces.jsonl",
                suite_version="public_v1",
                suite_hash=suite_hash(SUITE),
                world_hashes=world_hashes,
            )
            adapter = load_adapter(agent_name)
            manifest = run_items(items, adapter, spec, BudgetTracker(max_usd_per_run=150.0))
            (out_dir / "manifest.json").write_text(
                manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )

            records = list(read_traces(out_dir / "traces.jsonl"))
            connections = {w: duckdb.connect(str(p), read_only=True) for w, p in db_paths.items()}
            try:
                verdicts = score_run(
                    items,
                    records,
                    registries=registries,
                    grain_models=grain_models,
                    connections=connections,
                    reference_dates=reference_dates,
                    judge=None,
                )
                weights = {k: v for k, v in DEFAULT_WEIGHTS.items() if k != "faithfulness"}
                score = aggregate(verdicts, weights)
                result = render_report(
                    items,
                    records,
                    verdicts,
                    manifest,
                    registries=registries,
                    reference_dates=reference_dates,
                    weights=DEFAULT_WEIGHTS,
                    thresholds=DEFAULT_THRESHOLDS,
                    judge_configured=False,
                    out_path=out_dir / "report.html",
                )
            finally:
                for con in connections.values():
                    con.close()

            summary = {
                "agent": agent_name,
                "condition": condition,
                "suite_hash": spec.suite_hash,
                "items": manifest.totals.items,
                "ran_fine": result.extra["ran_fine"],
                "business_correct": result.extra["business_correct"],
                "overall_weighted": result.overall,
                "per_axis": {a: s.rate for a, s in score.per_axis.items()},
                "judge": "not evaluated (offline)",
                "cost_usd": manifest.totals.cost_usd,
            }
            (out_dir / "summary.json").write_text(
                json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/bench_results")
    run_roster(["naive"], ["closed", "open"], out)
