# Lessons — Phase 2 (Contracts and scorer core)

## What worked

Writing the golden fixtures as commented YAML with the arithmetic worked out by hand
(`# 50/10000 = 0.005 <= 0.005`) made review trivial and turned "who validates the
validator" into a concrete artifact. Purity paid off immediately: with no I/O in the
scorer, the 100% branch-coverage gate was reachable with fast tests (~1s), and the
focused `cov-core` target keeps the gate cheap enough to run on every `make check`.
Directional strictness (requests forbid extras, responses ignore extras but enforce
action-specific substance) resolved the lenient-vs-strict tension cleanly.

## What was harder than expected

Edge-rule design, not code. Gold = 0 has no defensible relative tolerance, counts cannot
be "approximately right", and `unknown` had to be prevented from quietly improving
scores — each needed an explicit, documented decision (ADR-0003) rather than an
implementation detail. One mypy subtlety: reusing a loop variable across two loops bound
it to the `Axis` Literal type from the first loop; distinct names fixed it. The
hypothesis scale-invariance property also needed a margin around the tolerance boundary,
since floating-point scaling cannot preserve exact ties.

## What I would do differently

Define the evidence-dict vocabulary (`rule`, `expected`, `actual`, `reason`,
`over_refusal`) as named constants from the start; the report layer (Phase 6) will
consume these keys and string literals in two places is one too many. Also consider
property-testing the action matrix against a table instead of enumerating fixtures —
though the explicit fixtures are better documentation, which is why they stayed.

## Carry-forward action

- Revisit the 0.5% tolerance default after the first real benchmark runs (RT-011); the
  per-item override is the escape hatch until then.
- `ambiguous_term` / `missing_dimension` were added to Item beyond the original §10
  sketch (mechanical matching needs them) — keep the item linter (Phase 5) aligned.
- The contracts are now frozen: any change = ADR + `make schemas` + version bump; the
  schema-drift golden test enforces the re-export half mechanically.
