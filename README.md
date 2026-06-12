# LedgerBench

[![ci](https://github.com/kartikeyamandhar/ledgerbench/actions/workflows/ci.yml/badge.svg)](https://github.com/kartikeyamandhar/ledgerbench/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](https://www.python.org/)
[![license](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)
[![status](https://img.shields.io/badge/status-pre--alpha-orange)](#status)

**LedgerBench measures whether analytics agents are _business-correct_, not merely _execution-correct_.**

An AI analyst can write SQL that runs cleanly and returns a confident number that is
business-wrong: the wrong metric definition, silent double-counting from a fan-out join,
answering an ambiguous question instead of clarifying, answering an unanswerable question
instead of refusing, or explaining assumptions that do not match the SQL it actually ran.
Existing benchmarks (Spider, BIRD) score execution accuracy, which is saturating and no
longer discriminates. LedgerBench scores the gap between "the query ran fine" and "the
answer was right" across five axes — and ships the chart that shows it.

## Five scoring axes

1. **Definitional correctness** — numeric reconciliation to gold within tolerance.
2. **Grain safety** — static analysis of the agent's SQL against declared grains; catches fan-out double-counting.
3. **Ambiguity handling** — the agent must clarify when the question is underspecified.
4. **Refusal correctness** — the agent must refuse when the question is unanswerable, naming what is missing.
5. **Explanation faithfulness** — stated assumptions must match the executed SQL.

## Two modes, one engine

- **Demo / benchmark** — a bundled deterministic fake company where every true answer is known by construction. The public benchmark.
- **BYO** — point the engine at a real dbt project, auto-generate the adversarial suite from your declared semantics, compute gold read-only, and grade your agent.

## The finding (v1.0, floor tier)

On the 150-item public bank, the deterministic offline baseline's queries **ran fine
100% of the time and were business-correct 9.3% of the time** — identically in closed
and open book, because the floor doesn't read documentation
([committed manifests](benchmark/results/)). Execution success and business
correctness are different quantities; this benchmark measures the distance for real
agents. Frontier-agent rows (Anthropic/OpenAI × closed/open × 3 seeds) land via
`scripts/run_benchmark.py` once API keys are configured — nothing is projected in
advance. **Leaderboard:** https://kartikeyamandhar.github.io/ledgerbench/ ·
**Technical report:** [docs/report.md](docs/report.md)

## Status

v1.0.0 — all eight phases complete: deterministic worlds, frozen contracts, the
golden-tested five-axis scorer, the fail-closed grain checker (TPR 1.000 / FPR 0.000 on
its published corpus), the SELECT-only sandboxed runner with kill-tests, the 150-item
bank with recipe-derived gold, the five-minute demo, BYO/dbt mode
([guide](docs/byo.md)), and release packaging.

## Quickstart

From a checkout (PyPI packaging lands in Phase 8):

```bash
git clone https://github.com/kartikeyamandhar/ledgerbench && cd ledgerbench
python3.11 -m venv agentic_flow && source agentic_flow/bin/activate
pip install -e .
ledgerbench demo          # ~35s: builds both worlds, runs the offline baseline, opens the report
```

No API keys, no network. The demo runs the deterministic naive baseline over all 150
items and renders the headline finding: on our machine, **100% of its queries ran fine
and 9% of its answers were business-correct**. That gap is the benchmark's point.

Other commands: `ledgerbench run -c ledgerbench.yaml` (config-driven, exit code 1 on
axis-threshold breach — the CI gate), `ledgerbench report` (re-render/re-score from
traces, no model calls), `ledgerbench validate` (lint the item bank, recompute gold),
`ledgerbench world build`.

### Develop

```bash
python3.11 -m venv agentic_flow
source agentic_flow/bin/activate
pip install -e ".[dev]"
pre-commit install
make check                # format check + lint + type + tests with coverage gate
```

## License

Apache-2.0. Copyright © 2026 Kartikeya Mandhar. See [LICENSE](LICENSE).
