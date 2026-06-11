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

## Module map

Phase 0 scaffolds the full module tree under `src/ledgerbench/` as docstring-only stubs.
