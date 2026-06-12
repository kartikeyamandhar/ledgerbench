"""Typer command-line entrypoint.

The CLI is a thin shell over library functions: every command delegates to an
importable function so the same behavior is available programmatically. Phase 1
adds ``world build``; the remaining commands land in Phase 6.
"""

from __future__ import annotations

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
