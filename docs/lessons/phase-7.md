# Lessons — Phase 7 (BYO mode)

## What worked

The architectural bet paid off exactly as designed: once `DbtSemantics` exposed the
same duck-typed surface as a `Rulebook` (ambiguities, absent dimensions, relationships,
`to_registry()`), the linter, gold compiler, executor, scorer, and reporter all ran on
a dbt project **unchanged** — the full BYO e2e test is wiring, not new machinery. The
coverage report turned "your project declares too little" from a failure mode into a
feature: the stripped fixture produces zero items and six precise reasons.

## What was harder than expected

Choosing the metrics channel. dbt-native metrics/semantic models vary wildly across
versions; the `meta.ledgerbench` block is a LedgerBench convention (RT-016) — explicit,
version-stable, and honest about being opt-in, but it means a stock project generates
only grain traps (from relationship tests) until the owner declares metrics. The
fail-closed detail that mattered: models without a `unique` test get a sentinel primary
key that can never match a join column, otherwise the grain checker would treat
undeclared tables as join-safe.

## What I would do differently

Build the stripped-fixture test first. Designing for graceful degradation up front
shaped better error messages everywhere (the version fence, the absent-dimension
verification) than retrofitting would have.

## Carry-forward action

- RT-016: MetricFlow/semantic-model ingestion is the post-launch path for projects
  that already declare metrics natively.
- The review command's edit path is minimally tested (approve/reject covered;
  interactive edit exercised manually) — fine for v1, note for community hardening.
- Snowflake seam: `connect_warehouse` is the single function to extend.
