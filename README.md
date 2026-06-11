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

## Status

Pre-alpha. Phase 0 (foundation) is the current milestone. The project is built in eight
gated phases: worlds, contracts + scorer, grain checker, runner, item bank, CLI + report,
BYO mode, and launch. The directory tree is scaffolded with stub modules; application
logic lands phase by phase.

## Quickstart

> _Finalized in Phase 6. The five-minute demo will be:_

```bash
pip install ledgerbench
ledgerbench demo          # builds the fake company, runs a baseline agent, opens a report
```

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
