# Lessons — Phase 0 (Foundation)

## What worked

Single-sourcing everything in `pyproject.toml` and routing the whole gate through one
`make check` target made the local/CI contract trivial: the same four steps (format check,
lint, type, tests+coverage) run identically in both places. Building the entire §9 tree as
pure-docstring stubs kept the "zero logic" rule mechanically true and let a single
walk-import test drive coverage to 100% without writing fake tests. `make check` was green
in ~4s on the first real run.

## What was harder than expected

Two non-obvious things. First, coverage on an empty skeleton: a naive "import the package"
test leaves every submodule uncovered and fails the 85% gate; the fix was a test that
`walk_packages`-imports every module, which both exercises top-level statements and guards
against hidden import errors. Second, tool version skew: the `ruff` pinned in
`.pre-commit-config.yaml` must match the `ruff` pip installs, or pre-commit and `make
check` disagree on formatting. Aligning the hook rev to the installed version
(`v0.15.16`) closed the gap.

## What I would do differently

Pin the pre-commit `ruff` rev to the intended ruff version from the start instead of a
stale placeholder. Decide the per-module 100% branch-coverage enforcement mechanism (a
dedicated check, not just config) before Phase 2 lands the first scorer logic, rather than
deferring it implicitly.

## Carry-forward action

- The operating manual (`CLAUDE.md`) is kept local-only by owner decision, so every
  committed doc must be self-contained — no links or section citations into it. Public
  docs were scrubbed accordingly in this phase; keep new docs self-contained.
- Wire the 100% branch-coverage gates on `scorer/` core and `runner/safety.py` in Phases
  2 and 4 when those modules gain logic (recorded in ADR-0001).
