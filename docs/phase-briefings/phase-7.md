# Phase 7 Briefing — BYO mode (the product engine)

Status: proceeding under standing autonomy grant (2026-06-12); briefing delivered with the build.
Depends on Phase 6. BYO is additive: demo mode is untouched.

**Objective:** point the same engine at a real dbt project — ingest declared semantics
into the *same* registry the bundled worlds use, generate the adversarial suite from
them, compute gold read-only on the user's warehouse, and gate their agent. This phase
proves the central architectural bet: rulebook YAML and a dbt manifest compile to the
same `DefinitionRegistry` + `GrainModel`, so everything downstream runs unchanged.

## 1. Concepts (theory level)

- **The architectural bet, cashed.** Since Phase 1, every consumer has depended on the
  registry abstractions, never on YAML. If that boundary held, BYO is "swap the loader."
  This phase is the proof; the sentence goes in the technical report's design section.
- **Declared semantics only (no fabrication).** Generators consume what the project
  *declares*: metrics with filters/exclusions → definitional traps; 1:N relationships
  carrying measures → grain traps; near-duplicate metric names → ambiguity; plausible
  dimensions absent from every model → refusal; declared calendars/timezones → period.
  Where a project declares too little, the answer is a **coverage report** that says
  which classes could not be generated and why — never invented semantics, never an LLM
  in the generation path (§17).
- **Human-in-the-loop where judgment lives.** Ambiguity and refusal items rest on
  judgments ("is this genuinely two-readinged for *your* business?") that the generator
  can propose but only the owner can approve. The `review` command makes approval an
  explicit, persisted, idempotent act; approvals freeze into a versioned suite.
- **Trust through restraint.** Generation and gold computation touch the user's
  warehouse read-only, through the same SELECT-only gate as agent SQL, with the query
  count reported before execution. "Read-only role required" is stated in red.

## 2. Design (architecture level)

- **`ingestion/dbt_manifest.py`:** parse `manifest.json` (schema versions **v11–v12**,
  dbt-core ~1.7–1.9; the `metadata.dbt_schema_version` is checked first and failure
  messages name the found vs supported versions and the fix). Extraction:
  models → tables; `unique` tests → primary keys/grains; `relationships` tests →
  many-to-one edges (FK semantics); metrics from model `meta.ledgerbench` blocks
  (measure/filters/exclusions/value_type) — the documented, version-stable channel —
  plus project-level declarations (`reporting_timezone`, `fiscal_year_start_month`,
  `absent_dimensions`, `ambiguous_terms`) from the project node's meta. Output:
  `Rulebook`-equivalent structures → the same `DefinitionRegistry` + `GrainModel`.
- **`generator/traps/*.py`:** one deterministic generator per class, each
  `(registry, grain_model, declarations, warehouse) -> list[Item] | reason`. Period
  windows derive from a read-only min/max probe (the last full month in range).
  Provenance (which dbt node produced each item) is embedded in the rubric text —
  the Item contract stays frozen. `generator/suite.py` gains `generate_suite(...)`
  returning items + a per-class `CoverageReport`.
- **`gold/compiler.py` seam:** `connect_warehouse(url)` — `duckdb:///path` opens
  read-only in v1; any other scheme raises with the Snowflake-post-launch message
  (RT-001). The compiler itself is unchanged — recipes are warehouse-agnostic SELECTs.
- **`review` command:** walks generated ambiguity/refusal items interactively
  (approve / edit the question / reject); other classes auto-approve. Decisions persist
  in a sidecar `decisions.json` keyed by item id — re-running skips decided items
  (idempotent); `--approve-all` exists for CI and the e2e test. Approvals freeze into a
  versioned suite JSONL that `validate`, `run`, and `report` consume unchanged.
- **`tests/fixtures/tiny_dbt_project/`:** a minimal committed project (models +
  schema.yml + a hand-trimmed committed `manifest.json` + a seeded DuckDB build script)
  exercising every generator class; a stripped variant (no tests, no meta) demonstrates
  graceful degradation via the coverage report.

## 3. Walkthrough (code level)

New/changed: `ingestion/dbt_manifest.py`; `generator/traps/{definitional,grain,
ambiguity,refusal,period,controls}.py`; `generator/suite.py` (+`generate_suite`,
`CoverageReport`); `gold/compiler.py` (+`connect_warehouse`); `cli.py` (+`generate`,
`review`); fixtures; tests (parser across both supported schema versions, generator
units per class, review persistence/idempotence, full e2e
generate → review → run(naive) → report on the fixture warehouse).

**Alternatives considered:** parsing model SQL to infer semantics (rejected: fabrication
risk; declared-only is the line); MetricFlow semantic-model ingestion (post-launch —
the meta channel is version-stable and explicit); interactive-only review (rejected:
CI needs `--approve-all`; interactivity is the default, not the only path); storing
provenance in a new Item field (rejected: contracts are frozen; rubric text carries it).

## 4. Red-team summary (§13)

- **Solutions Architect (leads):** dbt manifest drift is the known hazard (the schema
  version check + per-version fixtures are the mitigation; unsupported versions fail
  with the found/supported/fix message, not a stack trace).
- **Security Engineer:** warehouse credentials via URL/env only, never logged; the same
  `vet_sql` gate applies to generation probes and gold; connection opened read-only.
- **End User:** the coverage report is the honesty artifact — "we could not generate
  refusal items because your project declares no absent dimensions" is a feature.
- **SW Engineer:** generators are pure given (registry, declarations, probe results);
  the only I/O is the bounded min/max probe.
- **Staff Engineer:** `generate_suite` reuses `validate_items` as its own gate — the
  generated suite must lint clean before it is written.
- **Product Engineer:** `generate` prints the coverage report and the expected gold
  query count before computing anything.
- **DevOps:** the committed manifest fixture keeps dbt itself out of the dependency
  tree; e2e runs offline in CI.
- **Failure modes:** sparse real-world semantics (coverage report, never fabrication);
  manifest drift (version fence); warehouse cost (aggregate-only recipes, count
  reported first). **Register add: RT-016** — meta-block metrics are a LedgerBench
  convention, not dbt-native; risk of projects lacking them entirely; mitigated by the
  coverage report and documented examples; MetricFlow ingestion is the post-launch path.

## 5. Open decisions (resolved under autonomy)

1. Supported dbt manifest schema versions: v11–v12, checked first, actionable failure.
2. Metrics channel: `meta.ledgerbench` blocks (version-stable, explicit); MetricFlow
   later (RT-016).
3. Provenance lives in rubric text; the frozen Item contract is untouched.
4. `review` is interactive by default with `--approve-all` for automation; decisions
   sidecar keyed by item id gives idempotence.
5. Generated-suite ids: `byo-<class>-NNN`, version `generated_v1`.
