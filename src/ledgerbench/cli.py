"""Typer command-line entrypoint.

The CLI is a thin shell over library functions: every command delegates to an
importable function so the same behavior is available programmatically. Phase 1
adds ``world build``; Phase 5 adds ``validate``; the remaining commands land in
Phase 6.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from ledgerbench import worlds

app = typer.Typer(
    name="ledgerbench",
    help="Measure whether analytics agents are business-correct, not merely execution-correct.",
    no_args_is_help=True,
    add_completion=False,
)

world_app = typer.Typer(help="Build and inspect benchmark worlds.", no_args_is_help=True)
app.add_typer(world_app, name="world")

_console = Console()


@world_app.command("build")
def world_build(
    world: str = typer.Option(
        "all", "--world", help="World to build: a name (e.g. 'saas', 'finance') or 'all'."
    ),
    seed: int = typer.Option(42, "--seed", help="Deterministic generation seed."),
) -> None:
    """Build one or all bundled worlds into local ``.duckdb`` files.

    The databases are written under ``.ledgerbench/worlds/`` (gitignored) and are
    reproducible: the same seed yields byte-identical data.
    """
    available = worlds.available_worlds()
    if world == "all":
        targets = available
    elif world in available:
        targets = [world]
    else:
        known = ", ".join(available) or "(none)"
        _console.print(f"[red]Unknown world '{world}'.[/red] Available: {known}.")
        raise typer.Exit(code=2)

    if not targets:
        _console.print("[yellow]No worlds available to build.[/yellow]")
        raise typer.Exit(code=2)

    for name in targets:
        db_path = worlds.build_world(name, seed=seed)
        digest = worlds.digest_database(db_path)
        _console.print(f"[green]built[/green] {name}  ->  {db_path}  (digest {digest[:12]})")


@app.command("validate")
def validate(
    suite: Path = typer.Argument(  # noqa: B008 - typer evaluates defaults at import
        Path("benchmark/items/public_v1.jsonl"),
        help="Suite JSONL to lint.",
    ),
    gold: bool = typer.Option(
        True,
        "--gold/--no-gold",
        help="Also recompute every answer item's gold against freshly built worlds.",
    ),
    seed: int = typer.Option(42, "--seed", help="World build seed for gold recomputation."),
) -> None:
    """Lint an item suite: structure, preconditions, and (optionally) gold.

    Exits nonzero on any failure -- this is the CI gate for the item bank.
    """
    import duckdb

    from ledgerbench.generator.suite import PUBLIC_TAXONOMY, load_bank, validate_items
    from ledgerbench.ingestion.rulebook import load_rulebook

    try:
        items = load_bank(suite)
    except (OSError, ValueError) as exc:
        _console.print(f"[red]could not load suite:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    world_names = sorted({item.world for item in items})
    rulebooks = {
        name: load_rulebook(worlds.WORLDS_DIR / name / "rulebook.yaml") for name in world_names
    }

    connections = None
    if gold:
        _console.print(f"building worlds {world_names} (seed {seed}) for gold recomputation ...")
        connections = {
            name: duckdb.connect(str(worlds.build_world(name, seed=seed)), read_only=True)
            for name in world_names
        }

    expected = PUBLIC_TAXONOMY if len(items) == 150 else None
    try:
        report = validate_items(
            items, rulebooks, connections=connections, expected_taxonomy=expected
        )
    finally:
        for con in (connections or {}).values():
            con.close()

    if report.ok:
        _console.print(
            f"[green]suite valid[/green]: {report.checked_items} items, "
            f"{report.recomputed_gold} gold values recomputed"
        )
        return
    for error in report.errors:
        _console.print(f"[red]error[/red] {error}")
    _console.print(f"[red]{len(report.errors)} error(s).[/red]")
    raise typer.Exit(code=1)


# --- Phase 6: demo / run / report ------------------------------------------------


def _build_and_load(
    suite_path: Path, seed: int, limit: int | None
) -> tuple[
    list[Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    """Build worlds and load everything a scored run needs (CLI glue)."""
    import duckdb

    from ledgerbench.generator.suite import load_bank
    from ledgerbench.ingestion.rulebook import load_rulebook

    items = load_bank(suite_path)
    if limit is not None:
        items = items[:limit]
    world_names = sorted({item.world for item in items})

    db_paths: dict[str, Path] = {}
    schema_ddls: dict[str, str] = {}
    context_packs: dict[str, str] = {}
    rulebooks = {}
    for name in world_names:
        _console.print(f"building world [bold]{name}[/bold] (seed {seed}) ...")
        db_paths[name] = worlds.build_world(name, seed=seed)
        schema_ddls[name] = (worlds.WORLDS_DIR / name / "schema.sql").read_text(encoding="utf-8")
        context_packs[name] = (worlds.WORLDS_DIR / name / "rulebook.yaml").read_text(
            encoding="utf-8"
        )
        rulebooks[name] = load_rulebook(worlds.WORLDS_DIR / name / "rulebook.yaml")

    registries = {n: rb.to_registry() for n, rb in rulebooks.items()}
    grain_models = {n: rb.to_grain_model() for n, rb in rulebooks.items()}
    reference_dates = {n: rb.reference_date for n, rb in rulebooks.items()}
    connections = {n: duckdb.connect(str(p), read_only=True) for n, p in db_paths.items()}
    run_inputs = {
        "db_paths": db_paths,
        "schema_ddls": schema_ddls,
        "context_packs": context_packs,
        "world_hashes": {n: worlds.digest_database(p) for n, p in db_paths.items()},
    }
    return items, run_inputs, registries, grain_models, reference_dates, connections


def _execute_and_score(
    items: list[Any],
    run_inputs: dict[str, Any],
    registries: dict[str, Any],
    grain_models: dict[str, Any],
    reference_dates: dict[str, Any],
    connections: dict[str, Any],
    *,
    adapter_name: str,
    condition: str,
    seeds: tuple[int, ...],
    suite_path: Path,
    out_dir: Path,
    judge: Any | None,
    budget_kwargs: dict[str, Any] | None = None,
) -> tuple[Any, list[Any], list[Any]]:
    """Run one condition end to end; returns (manifest, records, verdicts)."""
    from ledgerbench.adapters.base import load_adapter
    from ledgerbench.generator.suite import suite_hash
    from ledgerbench.runner.budget import BudgetTracker
    from ledgerbench.runner.executor import RunSpec, run_items
    from ledgerbench.runner.trace import read_traces
    from ledgerbench.scorer.pipeline import score_run

    out_dir.mkdir(parents=True, exist_ok=True)
    trace_path = out_dir / "traces.jsonl"
    spec = RunSpec(
        db_paths=run_inputs["db_paths"],
        schema_ddls=run_inputs["schema_ddls"],
        context_packs=run_inputs["context_packs"],
        condition=condition,  # type: ignore[arg-type]
        seeds=seeds,
        trace_path=trace_path,
        suite_version=items[0].version if items else "unknown",
        suite_hash=suite_hash(suite_path),
        world_hashes=run_inputs["world_hashes"],
    )
    adapter = load_adapter(adapter_name)
    manifest = run_items(items, adapter, spec, BudgetTracker(**(budget_kwargs or {})))
    (out_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    records = list(read_traces(trace_path))
    verdicts = score_run(
        items,
        records,
        registries=registries,
        grain_models=grain_models,
        connections=connections,
        reference_dates=reference_dates,
        judge=judge,
    )
    return manifest, records, verdicts


@app.command("demo")
def demo(
    limit: int | None = typer.Option(
        None, "--limit", help="Run only the first N items (default: the full bank)."
    ),
    seed: int = typer.Option(42, "--seed", help="World build seed."),
    open_report: bool = typer.Option(
        True, "--open/--no-open", help="Open the rendered report in a browser."
    ),
) -> None:
    """The five-minute experience: build worlds, run the offline baseline, render.

    Needs no API keys and touches no network. The naive baseline answers every
    question -- including the ones it should clarify or refuse -- which is
    exactly the gap the report visualizes.
    """
    from ledgerbench.report.html import render_report

    suite_path = Path("benchmark/items/public_v1.jsonl")
    if not suite_path.is_file():
        _console.print(
            "[red]item bank not found.[/red] Run from a checkout of the repository "
            f"(missing {suite_path})."
        )
        raise typer.Exit(code=2)

    items, run_inputs, registries, grain_models, reference_dates, connections = _build_and_load(
        suite_path, seed, limit
    )
    out_dir = Path(".ledgerbench/demo")
    try:
        _console.print(f"running [bold]naive[/bold] adapter on {len(items)} items (open book) ...")
        manifest, records, verdicts = _execute_and_score(
            items,
            run_inputs,
            registries,
            grain_models,
            reference_dates,
            connections,
            adapter_name="naive",
            condition="open",
            seeds=(seed,),
            suite_path=suite_path,
            out_dir=out_dir,
            judge=None,
        )
        from ledgerbench.config import DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS

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

    _console.print(
        f"\n[green]demo complete[/green]: ran fine "
        f"{result.extra['ran_fine'] * 100:.0f}% vs business-correct "
        f"{result.extra['business_correct'] * 100:.0f}% "
        f"(weighted overall {result.overall * 100:.1f}%)"
    )
    _console.print(f"report: {result.path}  ({result.size_bytes / 1024:.0f} KiB)")
    if result.breaches:
        _console.print(
            f"[yellow]threshold breaches (informational in demo): "
            f"{', '.join(result.breaches)}[/yellow]"
        )
    if open_report:
        typer.launch(str(result.path.resolve()))


@app.command("run")
def run(
    config_path: Path = typer.Option(  # noqa: B008 - typer evaluates defaults at import
        Path("ledgerbench.yaml"), "--config", "-c", help="Path to ledgerbench.yaml."
    ),
    use_judge: bool = typer.Option(
        False,
        "--judge/--no-judge",
        help="Enable the live faithfulness judge (requires ANTHROPIC_API_KEY; costs money).",
    ),
    limit: int | None = typer.Option(None, "--limit", help="Run only the first N items."),
) -> None:
    """Config-driven benchmark run; exit code 1 on any axis-threshold breach.

    Runs every condition in the config, renders one report per condition, and
    adds the closed-vs-open comparison when both are present.
    """
    from ledgerbench.config import load_config
    from ledgerbench.errors import LedgerBenchError
    from ledgerbench.report.html import render_report
    from ledgerbench.scorer.aggregate import aggregate

    try:
        config = load_config(config_path)
    except LedgerBenchError as exc:
        _console.print(f"[red]{exc}[/red]")
        _console.print("Copy ledgerbench.example.yaml to ledgerbench.yaml and edit it.")
        raise typer.Exit(code=2) from exc

    judge = None
    if use_judge:
        from ledgerbench.scorer.faithfulness import AnthropicJudge, CachingJudge

        judge = CachingJudge(AnthropicJudge(), cache_dir=Path(".ledgerbench/judge_cache"))

    items, run_inputs, registries, grain_models, reference_dates, connections = _build_and_load(
        config.suite, config.worlds.build_seed, limit
    )

    breached: list[str] = []
    axis_rates: dict[str, dict[str, float]] = {}
    try:
        for condition in config.conditions:
            out_dir = Path(".ledgerbench/runs") / f"{config.agent.adapter}-{condition}"
            _console.print(
                f"\nrunning [bold]{config.agent.adapter}[/bold] "
                f"({condition} book, {len(items)} items, seeds {list(config.repetitions.seeds)})"
            )
            manifest, records, verdicts = _execute_and_score(
                items,
                run_inputs,
                registries,
                grain_models,
                reference_dates,
                connections,
                adapter_name=config.agent.adapter,
                condition=condition,
                seeds=config.repetitions.seeds,
                suite_path=config.suite,
                out_dir=out_dir,
                judge=judge,
                budget_kwargs={
                    "max_calls_per_item": config.budget.max_calls_per_item,
                    "max_usd_per_run": config.budget.max_usd_per_run,
                },
            )
            effective_weights = dict(config.weights)
            if judge is None:
                effective_weights.pop("faithfulness", None)
            axis_rates[condition] = {
                axis: s.rate for axis, s in aggregate(verdicts, effective_weights).per_axis.items()
            }
            comparison = None
            if condition == "open" and "closed" in axis_rates:
                comparison = (axis_rates["closed"], axis_rates["open"])
            result = render_report(
                items,
                records,
                verdicts,
                manifest,
                registries=registries,
                reference_dates=reference_dates,
                weights=config.weights,
                thresholds=config.thresholds,
                judge_configured=judge is not None,
                out_path=out_dir / "report.html",
                comparison=comparison,
            )
            _console.print(
                f"[green]{condition} done[/green]: overall {result.overall * 100:.1f}% "
                f"-> {result.path}"
            )
            breached.extend(f"{condition}:{axis}" for axis in result.breaches)
    finally:
        for con in connections.values():
            con.close()

    if breached:
        _console.print(f"[red]threshold breaches:[/red] {', '.join(breached)}")
        raise typer.Exit(code=1)
    _console.print("[green]all axis thresholds met.[/green]")


@app.command("report")
def report(
    traces: Path = typer.Option(..., "--traces", help="Trace JSONL from a previous run."),  # noqa: B008
    manifest_path: Path = typer.Option(  # noqa: B008 - typer evaluates defaults at import
        ..., "--manifest", help="manifest.json from that run."
    ),
    suite: Path = typer.Option(  # noqa: B008 - typer evaluates defaults at import
        Path("benchmark/items/public_v1.jsonl"), "--suite", help="The suite that was run."
    ),
    out: Path = typer.Option(  # noqa: B008 - typer evaluates defaults at import
        Path(".ledgerbench/report.html"), "--out", help="Where to write the report."
    ),
    seed: int = typer.Option(42, "--seed", help="World build seed (must match the run)."),
) -> None:
    """Re-render (and re-score) a report from existing traces. No model calls.

    This is the auditability path: tweak tolerances or weights in code/config,
    re-run this command, and the old run is re-judged without touching an API.
    """
    from ledgerbench.config import DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS
    from ledgerbench.contracts.manifest import RunManifest
    from ledgerbench.report.html import render_report
    from ledgerbench.runner.trace import read_traces
    from ledgerbench.scorer.pipeline import score_run

    for path, label in ((traces, "traces"), (manifest_path, "manifest"), (suite, "suite")):
        if not path.is_file():
            _console.print(f"[red]{label} file not found:[/red] {path}")
            raise typer.Exit(code=2)

    manifest = RunManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    records = list(read_traces(traces))
    item_ids = {r.item_id for r in records}

    items, _run_inputs, registries, grain_models, reference_dates, connections = _build_and_load(
        suite, seed, None
    )
    items = [i for i in items if i.id in item_ids]
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
            out_path=out,
        )
    finally:
        for con in connections.values():
            con.close()
    _console.print(f"[green]re-rendered[/green] {result.path} ({result.size_bytes / 1024:.0f} KiB)")


# --- Phase 7: BYO mode ------------------------------------------------------------


@app.command("generate")
def generate(
    manifest: Path = typer.Option(  # noqa: B008 - typer evaluates defaults at import
        ..., "--manifest", help="Path to the dbt project's manifest.json."
    ),
    warehouse: str = typer.Option(
        ..., "--warehouse", help="Read-only warehouse URL (duckdb:////absolute/path.duckdb)."
    ),
    out: Path = typer.Option(  # noqa: B008
        Path("generated_items.jsonl"), "--out", help="Where to write the generated suite."
    ),
) -> None:
    """Generate an adversarial suite from a dbt project's declared semantics.

    Reads only what the project declares (metrics, tests, meta blocks); where a
    trap class cannot be generated, the coverage report says why -- nothing is
    fabricated. The warehouse is touched read-only, through the same SELECT-only
    gate as agent SQL.
    """
    from ledgerbench.errors import LedgerBenchError
    from ledgerbench.generator.suite import generate_suite
    from ledgerbench.gold.compiler import connect_warehouse
    from ledgerbench.ingestion.dbt_manifest import load_dbt_manifest

    try:
        semantics = load_dbt_manifest(manifest)
        con = connect_warehouse(warehouse)
    except LedgerBenchError as exc:
        _console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    try:
        items, coverage = generate_suite(semantics, con)
    finally:
        con.close()

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(item.model_dump_json(exclude_none=True) + "\n")

    _console.print(coverage.render())
    _console.print(
        f"\n[green]generated {len(items)} items[/green] -> {out}\n"
        f"Next: [bold]ledgerbench review {out}[/bold] to approve the ambiguity and "
        f"refusal items (only you can judge those), then run your agent against the "
        f"frozen suite."
    )


@app.command("review")
def review(
    suite: Path = typer.Argument(..., help="Generated suite JSONL to review."),  # noqa: B008
    out: Path = typer.Option(  # noqa: B008
        Path("approved_items.jsonl"), "--out", help="Where to write the approved suite."
    ),
    approve_all: bool = typer.Option(
        False,
        "--approve-all",
        help="Non-interactive: approve every pending item (CI / scripting).",
    ),
) -> None:
    """Walk generated ambiguity/refusal items; approve, edit, or reject each.

    Decisions persist in a sidecar (<suite>.decisions.json) keyed by item id,
    so re-running skips what you already decided -- the review is idempotent.
    Approvals freeze into the output suite; other classes pass through.
    """
    import json

    from ledgerbench.generator.suite import load_bank

    if not suite.is_file():
        _console.print(f"[red]suite not found:[/red] {suite}")
        raise typer.Exit(code=2)
    items = load_bank(suite)
    sidecar = suite.with_suffix(suite.suffix + ".decisions.json")
    decisions: dict[str, dict[str, str]] = (
        json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() else {}
    )

    needs_review = [i for i in items if i.trap_class in ("ambiguity", "refusal")]
    pending = [i for i in needs_review if i.id not in decisions]
    _console.print(
        f"{len(items)} items; {len(needs_review)} need review; "
        f"{len(needs_review) - len(pending)} already decided; {len(pending)} pending."
    )
    for item in pending:
        if approve_all:
            decisions[item.id] = {"action": "approve"}
            continue
        _console.print(f"\n[bold]{item.id}[/bold] ({item.trap_class}): {item.question}")
        _console.print(f"  rubric: {item.rubric}")
        choice = typer.prompt("approve / edit / reject [a/e/r]", default="a").lower()
        if choice.startswith("e"):
            new_question = typer.prompt("edited question", default=item.question)
            decisions[item.id] = {"action": "edit", "question": new_question}
        elif choice.startswith("r"):
            decisions[item.id] = {"action": "reject"}
        else:
            decisions[item.id] = {"action": "approve"}

    sidecar.write_text(json.dumps(decisions, indent=1, sort_keys=True), encoding="utf-8")

    approved = []
    for item in items:
        decision = decisions.get(item.id, {"action": "approve"})
        if decision["action"] == "reject":
            continue
        if decision["action"] == "edit":
            item = item.model_copy(update={"question": decision["question"]})
        approved.append(item)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for item in approved:
            handle.write(item.model_dump_json(exclude_none=True) + "\n")
    _console.print(
        f"[green]froze {len(approved)} approved items[/green] -> {out} (decisions: {sidecar.name})"
    )
