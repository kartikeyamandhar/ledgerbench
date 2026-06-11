"""Typer command-line entrypoint. Commands are implemented in Phase 6."""

import typer

app = typer.Typer(
    name="ledgerbench",
    help="Measure whether analytics agents are business-correct, not merely execution-correct.",
    no_args_is_help=True,
    add_completion=False,
)
