"""Roster benchmark runner (staged copy; lands as scripts/run_benchmark.py).

Runs agents x conditions x seeds over the public bank, writing committed-style
results: traces.jsonl + manifest.json + summary.json per (agent, condition).
Resumable: existing result directories with a manifest are skipped.
"""

from __future__ import annotations

import json
import os
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
DEFAULT_SEEDS = (11, 22, 33)
WORLD_SEED = 42


def _parse_spec(spec: str) -> tuple[str, str | None]:
    """Split an 'adapter' or 'adapter:model' roster spec."""
    name, _, model = spec.partition(":")
    return name, (model or None)


def _slug(model: str) -> str:
    return model.replace(":", "-").replace(".", "-").replace("/", "-")


def run_roster(
    agents: list[str],
    conditions: list[str],
    out_root: Path,
    *,
    use_judge: bool = False,
    max_usd_per_run: float = 30.0,
    seeds: tuple[int, ...] = DEFAULT_SEEDS,
) -> None:
    """Run each roster spec x condition over the public bank.

    Specs are ``adapter`` or ``adapter:model`` (e.g. ``anthropic:claude-haiku-
    4-5-20251001``). With ``use_judge`` (requires ANTHROPIC_API_KEY and a
    passed calibration), faithfulness is scored live: double-run, cached.
    """
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

    judge = None
    judge_label = "not evaluated (offline)"
    if use_judge:
        from ledgerbench.scorer.faithfulness import AnthropicJudge, CachingJudge

        judge = CachingJudge(AnthropicJudge(), cache_dir=Path(".ledgerbench/judge_cache"))
        judge_label = "claude-haiku double-run, cached (calibration agreement 0.90)"

    for spec_str in agents:
        agent_name, model = _parse_spec(spec_str)
        label = f"{agent_name}:{model}" if model else agent_name
        for condition in conditions:
            dir_name = (
                f"{agent_name}-{_slug(model)}-{condition}" if model else f"{agent_name}-{condition}"
            )
            out_dir = out_root / dir_name
            if (out_dir / "manifest.json").is_file():
                print(f"skip {out_dir} (manifest exists; resume semantics)")
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            print(f"== {label} / {condition} ==")
            spec = RunSpec(
                db_paths=db_paths,
                schema_ddls=schema_ddls,
                context_packs=context_packs,
                condition=condition,  # type: ignore[arg-type]
                seeds=seeds,
                trace_path=out_dir / "traces.jsonl",
                suite_version="public_v1",
                suite_hash=suite_hash(SUITE),
                world_hashes=world_hashes,
            )
            adapter = load_adapter(agent_name)
            if model is not None:
                adapter.model = model  # provider adapters expose this knob
            manifest = run_items(
                items, adapter, spec, BudgetTracker(max_usd_per_run=max_usd_per_run)
            )
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
                    judge=judge,
                )
                weights = (
                    dict(DEFAULT_WEIGHTS)
                    if judge is not None
                    else {k: v for k, v in DEFAULT_WEIGHTS.items() if k != "faithfulness"}
                )
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
                    judge_configured=judge is not None,
                    out_path=out_dir / "report.html",
                )
            finally:
                for con in connections.values():
                    con.close()

            summary = {
                "agent": label,
                "condition": condition,
                "suite_hash": spec.suite_hash,
                "items": manifest.totals.items,
                "ran_fine": result.extra["ran_fine"],
                "business_correct": result.extra["business_correct"],
                "overall_weighted": result.overall,
                "per_axis": {a: s.rate for a, s in score.per_axis.items()},
                "judge": judge_label,
                "cost_usd": manifest.totals.cost_usd,
            }
            (out_dir / "summary.json").write_text(
                json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    args = sys.argv[1:]
    seeds = DEFAULT_SEEDS
    cap = 30.0
    if "--seeds" in args:
        i = args.index("--seeds")
        seeds = tuple(int(s) for s in args[i + 1].split(","))
        del args[i : i + 2]
    if "--max-usd" in args:
        i = args.index("--max-usd")
        cap = float(args[i + 1])
        del args[i : i + 2]
    out = Path(args[0]) if args else Path("benchmark/results")
    roster = args[1:] or ["naive"]
    use_judge = bool(os.environ.get("ANTHROPIC_API_KEY"))
    run_roster(
        roster, ["closed", "open"], out, use_judge=use_judge, max_usd_per_run=cap, seeds=seeds
    )
