# Changelog

All notable changes to LedgerBench are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
Semantic Versioning. `v1.0.0` is reserved for the public launch (Phase 8).

## [Unreleased]

## [1.1.0] - 2026-06-12

### Added

- **Keyed benchmark results** (committed, append-only): claude-haiku-4-5 and
  gpt-4o-mini × {closed, open} over the public 150 ($1.62 total model spend, per-run
  hard caps). The A/B finding lands: the rulebook lifts gpt-4o-mini from 42.0% to 59.3%
  business-correct (haiku 38.0%→44.0%, single seed) with ran-fine at 100% throughout —
  and a ~40% open-book residual survives. Full analysis in `docs/report.md`, including
  the per-axis side effects (the rulebook *degrades* grain/refusal/faithfulness for
  mini) and haiku's open-book `value: null` malformed cluster (the contract binds).
- **Live judge calibration: 0.90 agreement** (gate ≥ 0.8) on the 20-case set; RT-014
  closed. Faithfulness scored live (double-run, cached) on all keyed rows.
- Roster runner flags: `--seeds`, `--max-usd`; per-model result directories and
  `adapter:model` roster specs.

### Fixed

- Adapters now extract the contract payload from real model transport: markdown fences
  and prose-wrapped JSON are unwrapped at the adapter layer; probe-budget exhaustion
  gets a final answer turn; probe engine errors (hallucinated columns) return to the
  model as feedback instead of crashing the host. Each fix carries a regression test
  and was found by live smoke runs before the campaign.
- Adapter system prompt no longer describes `value` as nullable for answers (it invited
  the haiku cluster above); reruns under the tightened prompt are future work.


## [1.0.0] - 2026-06-12

### Added

- Phase 8 (Launch): `release.yml` — tag → build (`twine check`-ed) → PyPI via OIDC
  trusted publishing (no stored token; activates on the one-time publisher
  registration) → Docker image to GHCR with an offline-demo container smoke test.
- `Dockerfile` (python:3.12-slim, non-root, demo as default command); wheel installs
  now work outside a checkout (`WORLDS_DIR` falls back to the working directory).
- Committed benchmark results, floor tier: naive × {closed, open} × 3 seeds over the
  public 150 — ran-fine 100%, business-correct 9.3%, identical across conditions (the
  floor ignores the rulebook; that is the demonstration). Traces gzipped (~50×;
  `read_traces` handles `.gz` transparently) + manifests + summaries, append-only.
- `scripts/run_benchmark.py` (roster runner: agents × conditions × seeds, resumable,
  $150 hard cap) and `scripts/build_leaderboard.py` (static no-JS page as a pure
  function of committed results).
- Leaderboard deployed via `pages.yml` to GitHub Pages (enabled):
  https://kartikeyamandhar.github.io/ledgerbench/ — per-axis columns beside the
  aggregate, provenance column with suite hash/seeds/cost, frontier rows marked pending.
- `docs/report.md`: the technical report (motivation, taxonomy, method, floor results,
  failure gallery from real traces, limitations, future work) — `[pending keyed runs]`
  markers where only real numbers may go.
- `docs/launch-punch-list.md`: the owner-gated steps with exact commands.
- README finding section; CITATION.cff at 1.0.0.


## [0.7.0] - 2026-06-12

### Added

- Phase 7 (BYO mode): point the engine at a real dbt project. The central bet cashed —
  `ingestion/dbt_manifest.py` compiles a manifest (schema v11–v12, version-fenced with
  actionable failures) into the *same* `DefinitionRegistry`/`GrainModel` the bundled
  worlds use, so everything downstream runs unchanged.
- Extraction from declared semantics only: models → tables; `unique` tests → grains
  (fail-closed sentinel when undeclared); `relationships` tests → cardinalities;
  `meta.ledgerbench.metrics` → metric definitions; `meta.ledgerbench_project` →
  timezone/fiscal/ambiguous-terms/absent-dimensions declarations (verified, e.g. a
  declared-absent dimension that exists is rejected).
- `generator/traps/*`: six deterministic per-class generators (no LLM anywhere);
  `generate_suite` lints its own output and returns a per-class **coverage report** —
  classes that cannot be generated are skipped with the reason, never fabricated.
  Fixture yields 28 traps, 20 with recomputed gold; the stripped fixture degrades to
  zero items with six named reasons.
- `ledgerbench generate` (prints coverage, writes the suite) and `ledgerbench review`
  (interactive approve/edit/reject for ambiguity/refusal items; `--approve-all` for
  automation; decisions persist in a sidecar — idempotent, byte-identical re-freeze).
- `gold/compiler.py::connect_warehouse`: read-only `duckdb://` URLs in v1; other
  schemes fail with the Snowflake-post-launch message (the adapter seam, RT-001).
- `tests/fixtures/tiny_dbt_project/`: committed models + schema.yml + hand-trimmed
  manifest (plus a stripped variant) + deterministic warehouse builder; full BYO e2e
  (generate → review → run naive → score → report) runs offline in CI.
- `docs/byo.md`: the guide, read-only role requirement up top.


## [0.6.0] - 2026-06-12

### Added

- Phase 6 (CLI, reporter, demo): `ledgerbench demo` — the five-minute experience (~35 s
  measured): builds both worlds, runs the offline naive baseline over the 150-item bank,
  scores all five axes, renders the report, opens it. No keys, no network.
- `scorer/pipeline.py`: traces → verdicts replay (axis 1 with live recipe-derived gold,
  axis 2 grain check, axes 3–4 action matrix mapped per item class, axis 5 with optional
  injected judge — absence is `na`/"not evaluated", never an agent failure; RT-015).
- `config.py`: validated `ledgerbench.yaml` (suite, agent, conditions, seeds, budget,
  tolerances, weights, thresholds).
- `report/`: single-file offline HTML — inline server-side SVG (renders with JavaScript
  disabled), headline gap bars, per-axis table with unknown counts and gate column,
  closed-vs-open comparison, failure gallery (question, agent SQL, gold SQL, evidence)
  via `<details>`, manifest + weights footer; autoescape on (XSS-tested); ~150 KiB.
- `ledgerbench run`: config-driven, multi-condition; **exit code 1 on axis-threshold
  breach** (the CI-gate behavior), 2 on usage errors. `ledgerbench report`: re-render and
  re-score from traces with zero model calls (the auditability path).
- CLI e2e tests (typer runner): demo, exit-code matrix, re-render, validate.
- README quickstart finalized with measured demo numbers.


## [0.5.0] - 2026-06-12

### Added

- Phase 5 (Item bank + faithfulness judge): `benchmark/items/public_v1.jsonl` — 150
  hand-authored items, taxonomy-exact (definitional 40, grain 30, ambiguity 25,
  refusal 20, period 15, control 20), spread across both worlds. Items carry gold
  *recipes* (rulebook metric + optional `extra_where`), never baked values.
- `gold/compiler.py`: recipe → mechanical SQL (filters + negated exclusions +
  window) → scalar gold; `reference_date` substitution; every compiled query passes
  the same safety gate as agent SQL; NULL/fractional-count gold is a defect, not a value.
- `generator/suite.py`: `load_bank`, `suite_hash`, and `validate_items` — the linter
  (unique ids, taxonomy counts, per-class preconditions declared in the world's
  rulebook, world isolation, full gold recomputation). Runs in CI; 105 recipes
  recompute in ~0.1 s against built worlds.
- `ledgerbench validate` CLI: the same linter as a command with exit codes.
- `scorer/faithfulness.py` (axis 5): deterministic sqlglot fact extraction (tables,
  joins, filters, exclusions, date bounds, aggregates); LLM judge confined to
  semantic match, double-run with agreement required (disagreement → `unknown`),
  content-hash cached, prompt versioned; `na` (judge never runs) without assumptions.
- Calibration set: 20 hand-labeled cases; CI pins extraction + plumbing;
  `scripts/judge_calibration.py` measures live judge agreement (gate ≥ 0.8; requires
  a key — pre-launch step).
- Docs: `benchmark/items/README.md` (taxonomy, authoring guide, anti-subjectivity
  argument), `docs/private-split.md` (the protocol, RT-004).


## [0.4.0] - 2026-06-12

### Added

- Phase 4 (Runner, adapters, safety): the security boundary. `runner/safety.py` —
  `vet_sql` (parse, single statement, SELECT-only, structural denylist, comments
  stripped) + `SafeExecutor` (timeout via interrupt timer, row cap, audit log).
- Kill-test corpus: 30 malicious fixtures in `tests/fixtures/malicious_sql/`, each
  asserted rejected **and** never executed (audit log empty). Permanent regression armor.
- `adapters/base.py`: `AgentAdapter` ABC + `ledgerbench.adapters` entry-point discovery;
  adapters get a gated, budget-counted `execute_sql` callback, never a DB handle.
- `adapters/naive.py`: offline deterministic baseline (no key, no network) — the
  adapter-in-100-lines worked example, now documented in CONTRIBUTING.md.
- `adapters/http_openai.py` / `adapters/anthropic.py`: httpx-based provider adapters
  with a sql_probe loop; mocked-transport tests; keys from env only, never logged.
- `runner/executor.py`: seeds × items orchestration, transport-only retries with
  backoff, streaming JSONL traces (no wall-clock — byte-identical reruns asserted),
  RunManifest emission with latency/cost totals.
- `runner/budget.py`: per-item call cap (fails the item) and run-level USD cap (clean
  abort with a valid partial manifest).
- `runner/trace.py`: deterministic TraceRecord + streaming writer/reader.
- `.github/workflows/smoke.yml`: the 10-item offline eval on every PR, no secrets.
- SECURITY.md rewritten around the three-layer model; CONTRIBUTING.md adapter guide.

## [0.3.0] - 2026-06-12

### Added

- Phase 3 (Static grain checker): `scorer/grain_check.py` decides — without executing —
  whether agent SQL inflates an aggregate through a join. Verdicts: `safe`, `unsafe`
  (offending join path + aggregate in evidence), `needs_distinct`, `unknown`.
- Fan-out model: equi-join edges oriented one→many from declared GrainModel
  cardinalities; per-source BFS over the join tree catches fan traps, chasm traps, and
  dimension measures summed across fact joins; pre-aggregation repairs recognized.
- Fail-closed fence (ADR-0004): unsupported constructs return `unknown` naming the
  construct — RIGHT/FULL/CROSS joins, USING, non-equi joins, window functions, set ops,
  nesting beyond one level, undeclared relationships, cyclic join graphs, and more.
- Labeled corpus (47 queries) with precision printed on every run and gated in CI:
  measured TPR 1.000, FPR 0.000, unknown rate 0.255; mean analysis < 50 ms/query.
- `empirical_inflation` helper: execution-based corroboration (secondary evidence only);
  `grain_axis_result` maps verdicts onto the scorer axis vocabulary.
- Docs: ADR-0004, the $100→$300 worked example and measured precision in
  `docs/architecture.md`.

## [0.2.0] - 2026-06-12

### Added

- Phase 2 (Contracts + scorer core): the five data contracts (Item, AgentRequest,
  AgentResponse, Verdict, RunManifest) as frozen pydantic models, with JSON Schemas
  exported to `docs/contracts/` (`make schemas`) and a golden test against silent drift.
- `parse_agent_response`: untrusted-input gate — malformed agent output becomes a
  `MalformedResponse` (scores zero, never raises); extras ignored, substance strict.
- Scorer core (pure functions): `reconcile` (relative tolerance 0.5% default, exact
  counts, exact-zero rule), `score_action` (full expected×actual matrix, term/dimension
  matching, over-refusal flag), `aggregate` + `roll_up_item` (fail-closed, weights echoed).
- Golden suite: 47 hand-verified fixtures (tolerance boundaries, every action-matrix
  cell, malformed payloads, aggregate cases) + hypothesis property tests (scale
  invariance, tolerance monotonicity, boundedness, parser never raises).
- CI-enforced 100% branch-coverage gate on scorer core (`make cov-core`).
- Docs: ADR-0003 (scoring rules), `docs/contracts.md`, architecture scorer section.

### Changed

- CI actions bumped (`checkout@v5`, `setup-python@v6`) to clear the Node 20 deprecation.

## [0.1.0] - 2026-06-11

### Added

- Phase 1 (Worlds): two deterministic fake companies, `saas` and `finance`, each with a
  `schema.sql` (DuckDB DDL with PK/FK), a seeded stdlib generator, and a `rulebook.yaml`
  that plants a precondition for every trap class.
- `registry/`: `DefinitionRegistry` (metrics) and `GrainModel` (table grains + relationship
  cardinalities, with fan-out detection) as immutable pydantic models.
- `ingestion/rulebook.py`: `load_rulebook` validates a rulebook (pydantic, unknown keys and
  bad references rejected) and projects it into the registry and grain model.
- `worlds.py` + `ledgerbench world build [--world all] [--seed N]`: build gitignored
  `.duckdb` worlds; same seed yields an identical content digest (`world_digest`).
- Typed errors (`RulebookError`, `RulebookValidationError`, `WorldBuildError`).
- Golden/unit tests: byte-identical determinism per world, referential integrity, the
  trap-class checklist, rulebook validation, and CLI behavior (98% coverage).
- Docs: ADR-0002 (rulebook as canonical semantic source), the worlds section of
  `docs/architecture.md`, and `docs/rulebook.md` (format reference).

## [0.0.1] - 2026-06-10

### Added

- Phase 0 (Foundation): fully tooled, CI-green project skeleton.
- `src/` layout package `ledgerbench` with the complete §9 module tree as
  docstring-only stubs (no application logic).
- Tooling single-sourced in `pyproject.toml`: hatchling build, ruff (lint + format,
  line length 100), mypy strict on `src`, pytest + coverage (85% global gate).
- `Makefile` with the `check` gate; `.pre-commit-config.yaml` (ruff, mypy, gitleaks,
  file hygiene); `.github/workflows/ci.yml` running `make check` on Python 3.11 and 3.12.
- Project docs: README, CONTRIBUTING, SECURITY, CITATION, this CHANGELOG, ADR-0001
  (toolchain and layout), and the Phase 0 briefing.
- `.gitignore`, `.env.example`, `ledgerbench.example.yaml`, and
  `.claude/settings.json` (`includeCoAuthoredBy: false`).
- Placeholder test: package imports and `__version__` matches installed metadata.

[Unreleased]: https://github.com/kartikeyamandhar/ledgerbench/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/kartikeyamandhar/ledgerbench/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/kartikeyamandhar/ledgerbench/compare/v0.7.0...v1.0.0
[0.7.0]: https://github.com/kartikeyamandhar/ledgerbench/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/kartikeyamandhar/ledgerbench/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/kartikeyamandhar/ledgerbench/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/kartikeyamandhar/ledgerbench/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/kartikeyamandhar/ledgerbench/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/kartikeyamandhar/ledgerbench/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/kartikeyamandhar/ledgerbench/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/kartikeyamandhar/ledgerbench/releases/tag/v0.0.1
