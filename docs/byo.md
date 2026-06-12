# BYO mode: point LedgerBench at your dbt project

BYO mode ingests your project's **declared** semantics, generates an adversarial suite
from them, computes gold read-only on your warehouse, and grades your agent — the same
engine as the public benchmark, pointed at your business.

> **⚠️ READ-ONLY ACCESS REQUIRED.** Use a warehouse role that can only `SELECT`.
> LedgerBench additionally opens its connection read-only and passes every statement —
> including its own gold queries and probes — through the same SELECT-only safety gate
> that sandboxes agent SQL. But the role is your guarantee; set it first.

## Supported input

- dbt manifest schema **v11–v12** (dbt-core ~1.7–1.9). The version is checked before
  anything else; unsupported manifests fail with the found version and the fix.
- Warehouse: `duckdb:////absolute/path.duckdb` in v1. The Snowflake seam is defined
  (`gold/compiler.py::connect_warehouse`) and lands post-launch.

## What gets generated from what

| You declare | We generate |
|---|---|
| `unique` tests | table grains / primary keys (models without one are treated fail-closed) |
| `relationships` tests | join cardinalities → **grain/fan-out traps** where the parent carries a metric |
| `meta.ledgerbench.metrics` (measure, filters, exclusions, value_type, time_column) | **definitional traps** (filtered metrics), **controls** (plain metrics), **period traps** (time_column + timezone) |
| `meta.ledgerbench_project.ambiguous_terms` | **ambiguity traps** (review required) |
| `meta.ledgerbench_project.absent_dimensions` | **refusal traps** (verified absent, review required) |

Where your project declares too little for a class, the **coverage report** says so and
why. Nothing is fabricated, and no LLM is anywhere in the generation path.

## The flow

```bash
ledgerbench generate --manifest target/manifest.json \
    --warehouse duckdb:////path/to/warehouse.duckdb --out generated.jsonl
ledgerbench review generated.jsonl --out approved.jsonl    # approve/edit/reject amb+ref items
ledgerbench validate approved.jsonl --no-gold              # lint the frozen suite
```

`review` persists decisions in a sidecar keyed by item id — re-running skips what you
already decided. Every generated item's rubric records which dbt node produced it.

Declaring metrics (in your model's `schema.yml`):

```yaml
models:
  - name: orders
    meta:
      ledgerbench:
        metrics:
          - id: revenue_net
            measure: sum(amount)
            value_type: numeric
            filters: ["status = 'completed'"]
            exclusions: ["refunded = true"]
            time_column: order_ts
      ledgerbench_project:
        reporting_timezone: America/New_York
        absent_dimensions: [acquisition_channel]
        ambiguous_terms:
          - term: revenue
            readings: [revenue_gross, revenue_net]
```

Gold queries are simple aggregates; the expected query count equals the number of
answer items in the suite and is visible before anything runs (`generate` prints the
coverage report first).
