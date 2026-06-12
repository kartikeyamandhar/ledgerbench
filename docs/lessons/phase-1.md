# Lessons — Phase 1 (Worlds)

## What worked

The rulebook → (`DefinitionRegistry`, `GrainModel`) projection kept the YAML in exactly one
place and gave every downstream phase a stable target; pydantic with `extra = "forbid"` plus
a model validator turned typos and dangling references (unknown table, duplicate metric id,
ambiguity naming a missing metric) into loud, typed failures. Hashing table *content* rather
than the raw `.duckdb` bytes made determinism both meaningful and version-stable. The
trap-class checklist test is the quiet hero: it is a construct-validity guard that fails the
build if a world ever stops being able to exercise a failure class.

## What was harder than expected

DuckDB inserts. A first cut using `executemany` with foreign-key enforcement ran ~28s per
world — right at the 30s ceiling. Wrapping each generator's inserts in one transaction and
trimming row counts to the low end of the 50k–100k band brought it to ~15–17s, but the per-row
binding cost of `executemany` is the real floor without adding a heavy dependency (pandas/Arrow
are out per the dependency rule). The test suite is ~3 minutes because a few independent builds
plus full-table digest hashing are inherently not cheap.

## What I would do differently

Reach for set-based generation in SQL (deterministic `hash(seed, i)` pseudo-randomness via
`range()`) from the start if build time becomes a constraint — it would cut builds to well under
a second and stay within the "use DuckDB SQL" guidance. Decide this before Phase 5, where CI
recomputes gold against freshly built worlds and build time compounds.

## Carry-forward action

- `src/ledgerbench/worlds.py` is not in CLAUDE.md section 9; it was added as the importable
  builder so the CLI stays a thin shell (documented in ADR-0002). Keep section 9 in mind when
  adding modules.
- World generators live under `benchmark/` and are ruff-linted and behaviorally tested (build +
  integrity + determinism) but not mypy-checked. If they grow logic, consider promoting shared
  helpers into the typed package.
- Phase 5 gold recomputation depends on these worlds; revisit build time then. See [[phase-0]].
