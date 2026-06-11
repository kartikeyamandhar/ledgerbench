# Contributing to LedgerBench

Thanks for your interest. LedgerBench is pre-alpha and the public surface is still
moving phase by phase; the most useful contributions right now are adapters and item
review once those phases land.

## Development setup

```bash
python3.11 -m venv agentic_flow
source agentic_flow/bin/activate
pip install -e ".[dev]"
pre-commit install
make check
```

`make check` runs format check + lint (ruff) + type check (mypy strict) + tests with the
coverage gate. CI runs the same thing on Python 3.11 and 3.12. Never push red.

## Standards

- Conventional Commits: `type(scope): summary` (`feat fix test docs chore refactor ci build`).
- Small, reviewable diffs; one logical change per commit.
- Typed and Google-style-docstringed public APIs; the docstring says _why_.
- Determinism: every stochastic path takes an explicit seed.

## Write an adapter in ~100 lines (the promise)

> _Fulfilled in Phase 4, with `adapters/naive.py` as the worked example._

An adapter wraps any agent so it speaks the fixed JSON contract (`AgentRequest` in,
`AgentResponse` out). Third parties add adapters via the `ledgerbench.adapters`
entry-point group — no fork required. The full guide, the ABC, and the naive baseline
land in Phase 4; this section will then carry the copy-pasteable template.

## Security

Never commit secrets; the gitleaks hook will block them. See [SECURITY.md](SECURITY.md)
for the model that governs execution of agent-generated SQL.
