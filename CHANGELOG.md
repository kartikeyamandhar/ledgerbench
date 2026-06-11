# Changelog

All notable changes to LedgerBench are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
Semantic Versioning. `v1.0.0` is reserved for the public launch (Phase 8).

## [Unreleased]

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

[Unreleased]: https://github.com/kartikeyamandhar/ledgerbench/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/kartikeyamandhar/ledgerbench/releases/tag/v0.0.1
