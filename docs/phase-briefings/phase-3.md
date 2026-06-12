# Phase 3 Briefing — Static grain checker

Status: proceeding under standing autonomy grant (2026-06-12); briefing delivered with the build.
Depends on Phase 2 (Verdict/AxisResult contracts).

**Objective:** prove grain safety of agent SQL *without executing it*. The technically
hardest module; the rule is **fail closed** — anything the analyzer does not fully
understand returns `unknown`, never a guess.

## 1. Concepts (theory level)

- **Static vs dynamic verification.** Dynamic checking (run it and look) requires execution
  — slow, warehouse-touching, and only as good as the data you ran against. Static analysis
  reads structure: if the join graph multiplies rows under an aggregate, the query is wrong
  *for every dataset*, not just this one. The price is incompleteness: SQL is too rich to
  decide everything statically, which is why `unknown` exists as a first-class verdict.
- **The fan trap, formally.** Result grain = the set of key combinations one output row
  represents. Joining `orders` (grain: order_id) to `shipments` (grain: shipment_id) via a
  1→N relationship coarsens nothing — it *multiplies*: each order row appears once per
  shipment. `sum(o.amount)` over that result counts each order N times ($100 × 3 shipments
  = $300). The chasm trap is the two-legged variant: two independent 1→N paths from a
  shared parent multiply each other (N×M rows per parent).
- **What makes a multiplied join safe again:** aggregating the N-side *before* the join
  (pre-aggregation subquery/CTE), counting distinct keys of the safe side
  (`count(DISTINCT o.order_id)`), or aggregating only columns from the N-side itself.
  The checker must recognize these repairs, or its false-positive rate makes it useless.
- **Verification independence (the oracle problem again).** The grain checker never sees
  gold and never executes; it derives its verdict from the *declared* GrainModel plus the
  query's structure. Independent evidence channels (value reconciliation, static structure,
  stated assumptions) are what let the benchmark triangulate *why* an answer is wrong.
- **Honest precision accounting.** A static analyzer earns trust by publishing its own
  error rates: TPR on known fan traps, FPR on known-clean queries, and the `unknown` rate —
  measured against a labeled corpus, printed in test output, recorded in docs. Hiding
  `unknown` inside `safe` would be the same sin the benchmark exists to catch.

## 2. Design (architecture level)

- **API (generic, scorer-independent):** `check_grain(sql: str, grain_model: GrainModel,
  *, dialect="duckdb") -> GrainCheckResult` where the result carries `verdict`
  (`safe | unsafe | needs_distinct | unknown`), `evidence` (offending join path, fan-out
  relationships, aggregates involved), and `unsupported` (the construct that forced
  `unknown`, when applicable). This module is the seed of the standalone CI-gate product:
  SQL + GrainModel in, verdict out; no imports from scorer/ or runner/.
- **Pipeline:** sqlglot parse (duckdb dialect) → `build_scope` (scope tree: resolves
  aliases, CTEs, subqueries to their sources — probed empirically before this design;
  naive `find_all(Table)` mis-resolves CTE names as base tables) → per-scope join graph →
  cardinality lookup against `GrainModel.relationship(from, to)` → aggregate inspection
  (which table's columns feed Sum/Avg/Count; DISTINCT detection) → verdict.
- **Supported constructs (the hard fence, documented):** single SELECT; plain INNER/LEFT
  joins with equality ON conditions; GROUP BY; aggregates Sum/Avg/Min/Max/Count; CTEs one
  level deep; subquery sources one level deep; pre-aggregation recognition (the N-side
  grouped to the join key before joining). Everything else — RIGHT/FULL/CROSS joins,
  non-equi joins, window functions, set ops, correlated subqueries, deeper nesting,
  unknown tables/relationships — routes to `unknown` with a named `unsupported` reason.
- **Verdict semantics:** `unsafe` = a measure from the 1-side is aggregated (non-DISTINCT)
  over a fanned-out join, with the path in evidence. `needs_distinct` = same structure but
  the aggregate is COUNT of a 1-side key without DISTINCT (the fix is syntactically
  trivial). `safe` = no fan-out, or every fanned aggregate is repaired. `unknown` = fence
  exceeded. Min/Max are fan-out-*insensitive* (duplicates don't change them) — treated safe.
- **Reliability:** recursion bounded by explicit depth limits; every AST node type either
  handled or counted into the `unsupported` evidence. **Performance:** target < 50 ms per
  query (parse + scope walk; no I/O). **Security:** parser only; never executes input.

## 3. Walkthrough (code level)

- `scorer/grain_check.py`: `GrainCheckResult` (frozen pydantic), `check_grain()`, scope
  walker, join-graph builder, aggregate classifier, pre-aggregation detector.
- Empirical cross-check helper `empirical_inflation(con, sql, dedup_keys)` used in tests
  as corroborating evidence only (ADR-0004: why empirical is secondary — it requires
  execution, which the primary path must not).
- `tests/golden/grain/corpus.yaml`: 40+ labeled queries — clean analytical queries
  (controls), fan traps, chasm traps, repaired variants (pre-agg, DISTINCT), and
  fence-exceeding constructs labeled `unknown`.
- `tests/golden/grain/test_grain_corpus.py`: runs the corpus, computes and *prints* TPR /
  FPR / unknown-rate, asserts TPR ≥ 0.90 on fan traps and FPR ≤ 0.05 on clean queries.
- Property test: adding a pre-aggregation subquery flips canonical `unsafe` fixtures to
  `safe`. Dialect edges: quoted identifiers, aliases, self-joins (self-join = same table
  both sides; relationship lookup keyed on table *names*, so flagged via declared
  self-relationships or routed `unknown`).
- Docs: worked $100→$300 example in architecture.md; ADR-0004 (fail-closed policy).

**Alternatives considered:** execute-and-compare as primary (rejected: requires execution,
defeats static guarantee; kept as secondary evidence); full relational-algebra cardinality
inference (rejected: research-grade complexity for marginal v1 gain; the fence + unknown
is honest); regex heuristics (rejected: unauditable, dialect-fragile).

## 4. Red-team summary (§13)

- **SW Engineer:** the corpus is the spec; every verdict change must move a labeled number.
- **Staff Engineer:** generic API (SQL + GrainModel in, result out) keeps the module
  reusable as a standalone gate; no scorer imports.
- **Solutions Architect:** duckdb dialect only in v1 (RT-001); unparseable SQL is rejected
  upstream by the Phase 4 safety gate anyway.
- **Product Engineer:** `needs_distinct` is actionable feedback, not just a red X.
- **DevOps:** corpus runs in milliseconds; precision numbers printed in CI logs every run.
- **Security Engineer:** parse-only; no execution path exists in this module.
- **End User:** evidence names the exact join path and relationship that fans out — the
  report can show "orders →(1:N)→ shipments multiplies sum(orders.amount)".
- **Failure modes:** silent mis-resolution of aliases/CTEs (mitigated: build_scope +
  fence); FPR creep as repairs get fancier (mitigated: labeled corpus gates both rates);
  complexity spiral (mitigated: the fence is a hard list, extensions need corpus rows).
- **Register: RT-002 already covers fail-closed publishing; add RT-012 — pre-aggregation
  recognition is heuristic; mitigated by corpus coverage of repaired variants.**

## 5. Open decisions (resolved under autonomy)

1. Min/Max treated fan-out-safe (duplicates cannot change them) — documented.
2. COUNT(*) over a fanned join = `unsafe` (it counts inflated rows); COUNT(1-side key)
   without DISTINCT = `needs_distinct`; COUNT(DISTINCT 1-side key) = `safe`.
3. LEFT joins analyzed like INNER for fan-out purposes (multiplication is what matters;
   null-extension doesn't repair it).
4. Self-joins: routed `unknown` in v1 unless the rulebook declares a self-relationship —
   honest fence over a guess.
