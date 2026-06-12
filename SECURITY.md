# Security policy

LedgerBench executes model-generated SQL. Security is a design constraint from the first
commit, not a later add-on. The enforcing code is `runner/safety.py`, covered by the
permanent kill-test corpus in `tests/fixtures/malicious_sql/`: every fixture must be
rejected by the gate **and** provably never reach the engine — the executor's audit log
stays empty. When a new bypass is imagined, it becomes a fixture forever.

Defense in depth, three layers: (1) the gate — parse, single statement, SELECT-only,
structural denylist, comments stripped on re-render; (2) read-only connections, so even
a gate bypass cannot write; (3) resource rails (statement timeout, row cap) bounding what
any legitimate-looking SELECT can do to the host. Adapters never receive a database
handle — the executor hands them a gated, budget-counted `execute_sql` callback, and that
callback is the only road to the data.

## The model that governs SQL execution

1. **SELECT-only gate.** Every model-generated statement is parsed with sqlglot before
   execution. Exactly one `SELECT` is allowed. DDL, DML, `COPY`, `EXPORT`, `ATTACH`,
   `INSTALL`, `LOAD`, `PRAGMA`, `SET`, and any table function that touches the filesystem
   or network (`read_csv`, `read_parquet`, `read_json`, `glob`, `http*`) are denied.
   Unparseable SQL is rejected, never executed.
2. **Read-only connections.** DuckDB connections for agent queries open read-only. BYO
   mode requires a read-only warehouse role and says so prominently.
3. **Hard limits.** Every agent query has a statement timeout (default 30s) and a row cap
   (default 100k), enforced in the runner.
4. **No telemetry.** Nothing leaves your machine except your own calls to your chosen
   model providers.
5. **Secrets via environment only.** Use `.env` (gitignored); `.env.example` documents the
   variables with placeholder values. The gitleaks pre-commit hook blocks accidental
   commits of secrets. Traces redact API keys by construction.
6. **Private split isolation.** The 30-item private evaluation split never enters this
   repository in any form — not in tests, fixtures, or docs.

## Reporting a vulnerability

This is a pre-alpha portfolio/research project. Please open a GitHub issue for
non-sensitive reports. For anything that should not be public, contact the maintainer
listed in `CITATION.cff` before disclosing.
