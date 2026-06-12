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

## Module map

Phase 0 scaffolds the full module tree under `src/ledgerbench/` as docstring-only stubs.
