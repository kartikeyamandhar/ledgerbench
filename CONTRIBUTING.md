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

## Write an adapter in ~100 lines (the promise, fulfilled)

An adapter wraps any agent so it speaks the fixed JSON contract. Subclass
`ledgerbench.adapters.base.AgentAdapter` and implement one method:

```python
from ledgerbench.adapters.base import AgentAdapter, ExecuteSql
from ledgerbench.contracts.agent_io import AgentRequest


class MyAdapter(AgentAdapter):
    name = "my_agent"

    def complete(self, request: AgentRequest, execute_sql: ExecuteSql) -> object:
        # 1. Show your agent the question, schema, and (open-book) rulebook:
        #    request.question, request.schema_ddl, request.context_pack
        # 2. If it wants to look at data first, run SQL through the gate:
        #    rows = execute_sql("SELECT ...")   # SELECT-only, read-only, capped,
        #                                       # counted against request.budget.max_calls
        # 3. Return the raw payload (dict or JSON string). Do NOT pre-validate:
        #    malformed output scores zero, and that is part of the measurement.
        return {"action": "answer", "value": 123.0, "sql": "SELECT ...", "confidence": 0.7}
```

Ground rules:

- **Never open your own database handle.** The `execute_sql` callback is the only road
  to the data; it is the security boundary (see [SECURITY.md](SECURITY.md)).
- Raise `ledgerbench.errors.AdapterError` only for transport/protocol failures — the
  runner retries those with backoff. A *bad answer* is returned and scored, never raised.
- Read credentials from the environment; never log them. Traces carry no headers.

The bundled examples are the spec: [`adapters/naive.py`](src/ledgerbench/adapters/naive.py)
(offline, deterministic, ~100 lines) and the two provider adapters
([`http_openai.py`](src/ledgerbench/adapters/http_openai.py),
[`anthropic.py`](src/ledgerbench/adapters/anthropic.py)) which add a probe loop.

Ship it without forking by declaring an entry point in your package:

```toml
[project.entry-points."ledgerbench.adapters"]
my_agent = "my_package.adapter:MyAdapter"
```

## Security

Never commit secrets; the gitleaks hook will block them. See [SECURITY.md](SECURITY.md)
for the model that governs execution of agent-generated SQL.
