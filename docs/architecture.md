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

## Module map

Phase 0 scaffolds the full module tree under `src/ledgerbench/` as docstring-only stubs.
