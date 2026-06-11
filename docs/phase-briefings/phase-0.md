# Phase 0 Briefing — Foundation

Status: approved 2026-06-10. Scope: project foundation only; **zero application logic**
(any function body beyond `pass`, a docstring, or `raise NotImplementedError` is a review
failure). Goal: a fully tooled, CI-green, pushable skeleton that every later phase drops
code into without touching configuration again.

## 1. Concepts (theory level)

Only what Phase 0 actually rests on; deeper benchmark theory is deferred to its phase.

- **`src/` layout & import hygiene.** Putting the package under `src/ledgerbench/` makes it
  importable only when installed, catching "works on my machine, missing from the wheel"
  bugs at test time and forbidding path hacks. Structural enforcement of "test what you ship."
- **Reproducible toolchain as a measurement precondition.** A benchmark's credibility
  starts with its own determinism: pinned deps + a committed `requirements.lock` make a
  reviewer's `make check` identical to the maintainer's. The first instance of the
  project's spine — ground truth by construction — applied to the build itself.
- **CI as an executable gate.** `make check` (format check + lint + type + tests with
  coverage) runs identically locally and in CI on 3.11 and 3.12; "green" is a binary merge
  precondition. The matrix backs the portability claim.
- **Security from commit zero.** gitleaks in pre-commit and `.env.example` placeholders
  mean no secret can enter history undetected, before any SQL executor exists.
- **Authorship integrity as a verifiable invariant.** Sole authorship is checked by
  `git log` at every phase close; `.claude/settings.json` + a no-trailers discipline
  enforce it mechanically.
- **Architecture as dependency direction.** Isolating `contracts/` so everything depends
  inward on it is established in the tree now, paid off when contracts get bodies (Phase 2).

**Deferred (not touched by Phase 0):** measurement theory / construct validity (Phase 2),
the oracle problem & verification independence (Phase 3/5), relational grain & fan traps
(Phase 3), selective prediction & calibration (Phase 5/8), Goodhart & contamination (Phase 5).

## 2. Design (architecture level)

- **Single source of truth:** `pyproject.toml` holds metadata, deps, and all tool config.
  Runtime deps, a `dev` extra, and a `providers` extra so CI never needs provider SDKs.
- **One gate, one command:** the `Makefile` `check` target is the dev/CI contract.
- **Reliability:** `requirements.lock` pins the transitive tree; CI uses pip caching.
- **Security:** gitleaks + large-file + yaml hooks; `.gitignore` covers `agentic_flow/`,
  `.env`, `*.duckdb`, `benchmark/results/local/`, caches. SECURITY.md documents §8 now.
- **Performance:** n/a for logic; record `make check` wall-time as the baseline.

## 3. Walkthrough — what was scaffolded

Every `.py` is docstring-only except `__init__.py` (carries `__version__`) and `cli.py`
(a bare Typer app shell — wiring, not logic).

- Repo: `git init`; `origin` → ledgerbench URL; repo-local identity (name `Kartikeya
  Mandhar` + chosen email); `.claude/settings.json` = `{"includeCoAuthoredBy": false}`;
  `agentic_flow/` venv created and gitignored.
- Config: `pyproject.toml`, `requirements.lock`, `Makefile`, `.pre-commit-config.yaml`,
  `.gitignore`, `.env.example`, `ledgerbench.example.yaml`.
- CI: `.github/workflows/ci.yml` (`make check` equivalent on 3.11 + 3.12, pip cache).
- Package: the full §9 `src/ledgerbench/` tree as stubs.
- Docs: LICENSE (Apache-2.0), README, CONTRIBUTING, SECURITY, CHANGELOG, CITATION,
  `docs/architecture.md` stub, ADR-0001, this briefing.
- Test: package imports and `__version__` matches installed metadata.
- Git workflow: branch `phase/0-foundation` → PR → squash → tag **`v0.0.1`** (documented
  exception so `v0.1.0` lands with Phase 1).

**Alternatives (see ADR-0001):** flat vs `src` layout; hatchling vs setuptools/pdm;
ruff vs black+flake8+isort; `requirements.txt` vs frozen lock; single vs matrix Python;
enforce coverage gates now vs configure-now / enforce-when-logic-exists.

## 4. Red-team summary (§13 applied to Phase 0)

- **SW/Staff Engineer:** over-scaffolding → build only the §9 tree; stubs are pure
  docstrings; the walk-import test would catch accidental import-time logic.
- **Solutions Architect:** toolchain that fights real stacks → std `pyproject` + ruff/mypy/
  pytest are universal; backend isolated in ADR-0001.
- **Product Engineer:** hard onboarding → one-command `make` targets + README quickstart.
- **DevOps:** CI flakiness / non-reproducible builds → pinned lock + pip cache; identical
  local/CI gate; wall-time baseline recorded.
- **Security:** secret entering history → gitleaks from commit one; §8 documented in
  SECURITY.md before any executor exists. (RT-005, the SELECT-only gate, is Phase 4.)
- **End User:** trust/provenance → sole-authorship is `git log`-verifiable; Apache-2.0.
- **Superior alternative that lost:** deferring CI to Phase 1 — rejected; CI must be green
  before any real code lands.

Proposed register addition (to apply on next CLAUDE.md update): **RT-009 — Phase 0
toolchain/lock drift → pinned lock + 3.11/3.12 matrix + ADR-0001.**

## 5. Open decisions (resolved at approval)

1. Commit email — chosen: `kartikeya.mandhar@yahoo.in` (real email; public in history;
   must be verified on the GitHub account for profile attribution).
2. Build backend — **hatchling**.
3. Identity scope — **repo-local** (global config untouched).
4. CITATION.cff — author "Kartikeya Mandhar", 2026, v0.0.1, ORCID left blank to fill in.
