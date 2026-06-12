"""Typer command-line entrypoint.

The CLI is a thin shell over library functions: every command delegates to an
importable function so the same behavior is available programmatically. Phase 1
adds ``world build``; Phase 5 adds ``validate``; the remaining commands land in
Phase 6.
"""

from __future__ import annotations

from pathlib import Path

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
