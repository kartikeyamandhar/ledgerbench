# LedgerBench architecture

> Stub. This document grows phase by phase. Phase 1 adds the worlds section; Phase 2 the
> contracts and scorer; Phase 3 the worked grain-trap example; Phase 6 finalizes it for v0.

## Overview

LedgerBench is a pipeline that grades an analytics agent on whether its answers are
business-correct, not merely whether its SQL executed:

```
dataset (schemas + questions + gold)
  -> agent under test (pluggable adapter, fixed JSON contract)
  -> DuckDB execution (SELECT-only safety gate)
  -> five-axis scorer
  -> report (per-axis scores, gap chart, failure gallery, CI exit code)
```

## Dependency direction

Data contracts (`contracts/`) are the dependency sink: every other module depends inward
on them, never the reverse. Semantic sources (rulebook YAML now, dbt manifests later)
compile into the same `DefinitionRegistry` + `GrainModel`, so downstream code never sees
raw YAML — which is what lets BYO mode swap the loader and change nothing else.

The executor knows nothing about scoring and the scorer knows nothing about execution;
per-item traces are the only interface between them, which is what makes re-scoring old
runs and counterfactual replay possible.

## Worlds (Phase 1)

A *world* is a deterministic fake company: a `schema.sql`, a seeded `generate.py`, and a
`rulebook.yaml`, under `benchmark/worlds/<name>/`. Two ship in v1:

- **saas** — customers, subscriptions, users, orders, shipments, events.
- **finance** — accounts, a February-start fiscal calendar, transactions, ledger entries.

Each world plants a precondition for every trap class, so the benchmark can actually
exercise what it claims to measure:

| Trap class | saas | finance |
|---|---|---|
| definitional | `revenue` = completed orders, refunds excluded | `net_revenue` excludes void/pending |
| grain (fan-out) | orders → shipments (1→many) | transactions → ledger_entries (1→many) |
| ambiguity | `active_users_7d` vs `active_users_30d` | gross vs net `revenue` |
| refusal | no `acquisition_channel` dimension | no `cost_center` dimension |
| period / timezone | UTC `event_ts` + reporting tz | fiscal offset + UTC `txn_ts` + reporting tz |
| control | `order_count` (clean) | `transaction_count` (clean) |

The **grain fan-out** is the precondition Phase 3 will catch statically: a measure anchored
on the "one" side (e.g. `orders.amount`) is inflated when joined to the "many" side
(`shipments`). Deliberate, documented nulls and duplicates keep the data realistic without
making gold uncomputable.

**Flow.** `ingestion/rulebook.py` validates `rulebook.yaml` (pydantic) and projects it into a
`DefinitionRegistry` (metrics) and a `GrainModel` (grains + cardinalities) — the only place
YAML is read. `worlds.py` runs the schema, invokes the generator, and writes a gitignored
`.duckdb`; `ledgerbench world build [--world all] [--seed N]` is the CLI shell. Builds are
deterministic: the same seed yields an identical content digest (`world_digest`); a different
seed changes the data but not the schema. See ADR-0002 and the
[rulebook format reference](rulebook.md).

## Contracts and scorer core (Phase 2)

The five data contracts (Item, AgentRequest, AgentResponse, Verdict, RunManifest) are
frozen pydantic models in `contracts/` — the dependency sink — with JSON Schemas exported
to `docs/contracts/` and golden-tested against drift (see the
[contracts reference](contracts.md)).

The scorer core is three pure functions (no I/O, no globals, no clock):

- `scorer/reconcile.py` — axis 1: relative tolerance (default 0.5%, per-item override),
  exact match for counts, exact-zero rule at gold = 0.
- `scorer/actions.py` — axes 3–4: the expected×actual action matrix; clarifications must
  reference the ambiguous term, refusals must name the missing dimension, and refusing an
  answerable item is flagged as over-refusal.
- `scorer/aggregate.py` — item roll-up and the weighted suite score; `unknown` counts
  against, `na` renormalizes, weights echoed in the output.

"Who validates the validator" is answered by the **golden suite**
(`tests/golden/scorer/`): hand-verified fixtures covering tolerance boundaries, every
action-matrix cell, and malformed payloads, plus property tests (scale invariance,
tolerance monotonicity, boundedness, parser never raises). The scorer core carries a
CI-enforced 100% branch-coverage gate (`make cov-core`). Rules in
[ADR-0003](decisions/ADR-0003.md).

## The grain checker (Phase 3)

**The worked example.** An order worth $100 ships in 3 boxes. `orders` is one row per
order; `shipments` is one row per box, with `shipments.order_id → orders.order_id`
declared `many_to_one`. An agent answering "total revenue" writes:

```sql
SELECT sum(o.amount)
FROM orders o JOIN shipments s ON o.order_id = s.order_id;
```

The join result has one row per *shipment*, so the $100 order appears three times and
the query returns **$300**. It executes cleanly; it is business-wrong. The checker flags
it `unsafe` with evidence `orders -> shipments (one_to_many)` and the offending
aggregate `SUM(o.amount)` — statically, without executing anything.

**How it decides** (`scorer/grain_check.py`): parse (sqlglot, duckdb dialect) → resolve
scopes (aliases, CTEs, derived tables) → build the equi-join graph, orienting each edge
one→many from the declared `GrainModel` cardinalities → a source's rows are duplicated
exactly when a BFS away from it crosses an edge in the one→many direction (this one rule
catches fan traps, chasm traps, and dimension measures summed across fact joins, while
star/snowflake rollups stay clean) → classify each aggregate: SUM/AVG of a duplicated
source is `unsafe`; COUNT of one is `needs_distinct`; MIN/MAX are duplicate-insensitive;
COUNT(*) is unsafe only when no source is duplicate-free. Pre-aggregating the many side
(GROUP BY or DISTINCT to the join key) is recognized as the repair and flips the verdict
to `safe`.

**The fence (fail closed, ADR-0004).** Supported: single SELECT, INNER/LEFT equi-joins,
GROUP BY/HAVING, SUM/AVG/COUNT/MIN/MAX, one level of CTE/derived-table/WHERE-subquery
nesting. Everything else returns `unknown` naming the construct — never a guess.

**Measured precision** (the labeled corpus in `tests/golden/grain/`, printed by the test
suite on every run): corpus 47 queries (15 traps, 20 clean, 12 out-of-fence) —
**TPR 1.000, FPR 0.000, unknown rate 0.255**; gates asserted in CI are TPR ≥ 0.90 and
FPR ≤ 0.05. Mean analysis time is well under the 50 ms/query budget. An execution-based
helper (`empirical_inflation`) corroborates verdicts in tests — secondary evidence only.

## Module map

Phase 0 scaffolds the full module tree under `src/ledgerbench/` as docstring-only stubs.
