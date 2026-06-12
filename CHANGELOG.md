# Changelog

All notable changes to LedgerBench are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
Semantic Versioning. `v1.0.0` is reserved for the public launch (Phase 8).

## [Unreleased]

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

[Unreleased]: https://github.com/kartikeyamandhar/ledgerbench/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/kartikeyamandhar/ledgerbench/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/kartikeyamandhar/ledgerbench/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/kartikeyamandhar/ledgerbench/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/kartikeyamandhar/ledgerbench/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/kartikeyamandhar/ledgerbench/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/kartikeyamandhar/ledgerbench/releases/tag/v0.0.1
