# Rulebook format reference

A `rulebook.yaml` declares one world's semantics. It is validated by
`ledgerbench.ingestion.rulebook.load_rulebook`, which rejects anything malformed or
internally inconsistent (an unknown table reference, a duplicate metric id, an ambiguity
that names a metric that does not exist). Unknown keys are rejected (`extra = forbid`), so
typos fail loudly. The full, worked examples are
[`benchmark/worlds/saas/rulebook.yaml`](../benchmark/worlds/saas/rulebook.yaml) and
[`benchmark/worlds/finance/rulebook.yaml`](../benchmark/worlds/finance/rulebook.yaml).

## Top-level fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `world` | string | yes | World name; matches the directory under `benchmark/worlds/`. |
| `description` | string | no | Free text. |
| `timezone` | string | no | Storage timezone for timestamps (default `UTC`). |
| `reporting_timezone` | string \| null | no | Declared reporting tz; a period/timezone precondition. |
| `fiscal_year_start_month` | int 1–12 | no | Default `1`. A value ≠ 1 is the fiscal-offset precondition. |
| `reference_date` | date | yes | Anchor for windowed metrics (e.g. active-in-last-N-days). |
| `tables` | list | yes (≥1) | See below. |
| `relationships` | list | no | See below. |
| `metrics` | list | yes (≥1) | See below. |
| `ambiguities` | list | no | Documented ambiguous terms (ambiguity preconditions). |
| `absent_dimensions` | list | no | Plausible-but-absent dimensions (refusal preconditions). |
| `irregularities` | list | no | Documented planted nulls/duplicates. |

## Sub-objects

**table** — `name`, `grain` (list of columns), `primary_key` (list), optional `description`.

**relationship** — `name`, `from_table`, `to_table`, `from_columns`, `to_columns`,
`cardinality` (`one_to_one` | `one_to_many` | `many_to_one` | `many_to_many`). Cardinality is
read `from_table → to_table`; the inverse is inferred, so declaring `shipments → orders` as
`many_to_one` answers the `orders → shipments` (`one_to_many`) fan-out query.

**metric** — `id` (unique), `description`, `base_table`, `measure` (e.g. `sum(amount)`),
`value_type` (`numeric` reconciles within tolerance; `count` must match exactly), `grain`,
optional `filters` and `exclusions` (kept separate so a report can explain what was left out).

**ambiguity** — `term`, `readings` (≥2 metric ids), optional `note`.

**absent_dimension** — `name`, optional `note`.

**irregularity** — `table`, `kind` (`nulls` | `duplicates`), optional `column`, optional `note`.

## What the loader produces

`load_rulebook(path)` returns a validated `Rulebook`. From it:

- `rulebook.to_registry()` → a `DefinitionRegistry` (metrics by id), consumed by gold
  compilation and the scorer.
- `rulebook.to_grain_model()` → a `GrainModel` (table grains + relationship cardinalities),
  consumed by the static grain checker.

Nothing downstream reads YAML; a dbt manifest will compile into the same two structures in
Phase 7 (see [ADR-0002](decisions/ADR-0002.md)).
