# Changelog

All notable changes to LedgerBench are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
Semantic Versioning. `v1.0.0` is reserved for the public launch (Phase 8).

## [Unreleased]

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

[Unreleased]: https://github.com/kartikeyamandhar/ledgerbench/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/kartikeyamandhar/ledgerbench/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/kartikeyamandhar/ledgerbench/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/kartikeyamandhar/ledgerbench/releases/tag/v0.0.1
