# Phase 4 Briefing — Runner, adapters, safety

Status: proceeding under standing autonomy grant (2026-06-12); briefing delivered with the build.
Depends on Phase 2 (contracts). This phase is **the security boundary** of the project.

**Objective:** execute any agent against any item list under hard safety and budget rails,
with full reproducibility evidence. The executor knows nothing about scoring; traces are
the only interface between execution and scoring.

## 1. Concepts (theory level)

- **The security boundary.** This tool's defining risk: it executes model-generated SQL.
  The defense is layered: (1) a static gate (`safety.py`) that parses and vets every
  statement before execution — single SELECT only, denylist of DDL/DML/file/network
  constructs, unparseable = rejected; (2) read-only DuckDB connections, so even a gate
  bypass cannot write; (3) hard resource rails (statement timeout, row cap) so even a
  legitimate SELECT cannot exhaust the host. Kill-tests are permanent regression armor:
  every imagined bypass becomes a fixture forever (RT-005).
- **Defense in depth vs single perfect gate.** No parser-based gate is provably complete
  against a hostile model. That is why the connection is read-only *and* resource-capped:
  the gate failing must not be catastrophic. The audit log (every SQL the executor
  actually ran) exists so tests can assert the *negative* — blocked statements were never
  executed, not merely errored.
- **Reproducibility discipline.** Trace files contain no wall-clock and no latencies —
  only deterministic content (request, response, execution result, seed). Same seed +
  same offline adapter ⇒ byte-identical traces, asserted in tests. Volatile data
  (timestamps, latency percentiles, cost) lives in the RunManifest, which is metadata
  about a run, not evidence of agent behavior.
- **Separation of execution and judgment.** The executor emits traces; the scorer (Phase
  6 wiring) consumes them. This is what makes counterfactual re-scoring possible — an old
  run can be re-graded under new tolerances without calling any model again.
- **Budget as a hard rail, not a hint.** Cost caps abort the run with a clean partial
  manifest. An abort that corrupts state would teach users to disable the cap.

## 2. Design (architecture level)

- **`runner/safety.py`** — `vet_sql(sql) -> str` (normalized single statement or raises
  `SQLSafetyError` naming the violation) and `SafeExecutor` (wraps a read-only DuckDB
  connection; enforces vetting, statement timeout via interrupt timer, row cap; appends
  every executed statement to an audit log). Gate rules per the security policy: sqlglot
  parse (duckdb dialect); exactly one statement; root must be SELECT; deny DDL/DML, COPY,
  EXPORT, ATTACH/DETACH, INSTALL/LOAD, PRAGMA, SET/RESET, CALL, transactions, and any
  table function or function call matching the file/network denylist (`read_*`, `glob`,
  `http*`, `getenv`, ...). Unparseable SQL is rejected, never executed.
- **`adapters/base.py`** — `AgentAdapter` ABC: `name`, `complete(request, execute_sql)
  -> object` returning the *raw* payload (parsed centrally by the executor — one
  untrusted-input boundary). `execute_sql` is an executor-provided, safety-gated,
  budget-counted callback so agentic adapters can run SQL while reasoning
  (`budget.max_calls` = max SQL executions per item). Discovery: built-ins plus the
  `ledgerbench.adapters` entry-point group, so third parties add adapters without forking.
- **`adapters/naive.py`** — deterministic offline baseline: template SQL from question
  keywords + schema DDL (no API key, no network). Always answers — by design it walks
  into every trap, which is exactly what a floor baseline is for.
- **`adapters/http_openai.py` / `adapters/anthropic.py`** — thin httpx clients (no SDK
  dependency in the runtime path; the `providers` extra remains for users who want SDKs).
  Two-step loop within budget: model proposes SQL → adapter executes via the gated
  callback → model sees rows → final JSON. API keys from env only; never logged; traces
  carry no credentials by construction. Tested with mocked transports; never live in CI.
- **`runner/executor.py`** — orchestrates: for each item × seed: build request (closed:
  schema only; open: schema + context pack), call adapter (transport-only retries with
  exponential backoff — never retry on model "wrongness"), parse response, execute
  `response.sql` through the gate for the trace record, account cost/latency in memory,
  stream the trace record to JSONL. Emits RunManifest at the end (or a valid partial
  manifest on budget abort).
- **`runner/budget.py`** — `BudgetTracker`: per-item call cap and run-level USD cap;
  raising `BudgetExceededError` triggers the clean-abort path.
- **`runner/trace.py`** — frozen `TraceRecord` model + streaming writer + reader;
  deterministic serialization (sorted keys, no volatile fields).
- **`.github/workflows/smoke.yml`** — on every PR: build the saas world, run 10 fixture
  items against the naive adapter (no secrets), assert traces + manifest + determinism.

## 3. Walkthrough (code level)

New: `errors.py` gains `SQLSafetyError`, `BudgetExceededError`, `AdapterError`;
`tests/fixtures/malicious_sql/` (the kill-test corpus: DDL, DML, COPY out, ATTACH,
INSTALL/LOAD, PRAGMA/SET, read_csv/read_parquet/glob/http table functions,
multi-statement, comment smuggling, CTE-wrapped DML, unparseable garbage);
`tests/smoke/items_smoke.jsonl` (10 schema-valid items with literal gold values — the
public bank is Phase 5); executor unit tests with a scripted mock adapter (timeouts,
retries, malformed responses, budget abort); determinism test (two runs, byte-equal
traces).

**Alternatives considered:** executing agent SQL inside adapters (rejected: would
scatter the security boundary; the callback centralizes it); provider SDKs in the
runtime path (rejected: httpx keeps the dependency tree small and the mocks honest);
timestamps in traces (rejected: breaks byte-reproducibility; volatile data belongs to
the manifest); a kill-test "blocklist of strings" (rejected: parse-based vetting plus
structural checks; string matching is trivially smuggled past).

## 4. Red-team summary (§13)

- **Security Engineer (leads this phase):** bypass attempts live forever as fixtures;
  the audit log lets tests assert zero executions, not just "an error happened";
  read-only + timeout + row cap bound the blast radius of any future gate gap.
- **SW Engineer:** executor logic is tested with a deterministic mock adapter; retries
  are transport-only with bounded backoff; every failure path produces a trace record.
- **Staff Engineer:** traces-as-interface decouples execution from scoring permanently;
  the adapter ABC + entry points are the extension seam (the 100-line promise).
- **Solutions Architect:** httpx-only adapters mean the OpenAI-compatible adapter works
  against any compatible endpoint (vLLM, together, etc.) via `endpoint` config.
- **Product Engineer:** the naive adapter makes the demo free and instant — no keys.
- **DevOps:** smoke.yml exercises the full pipeline on every PR with zero secrets;
  traces stream (no memory growth on large rosters).
- **End User:** "read-only, capped, audited" is the sentence that earns warehouse access.
- **Failure modes:** dialect quirks smuggling writes (kill-tests + read-only floor);
  provider nondeterminism breaking claims (model snapshot ids recorded; variance
  reported in Phase 8, not hidden); cost runaway (hard USD cap, low default).
- **Register adds:** RT-013 — execute-callback design centralizes the gate; risk of an
  adapter bypassing it with its own DB handle; mitigated: adapters receive no DB path,
  only the callback, and the contract documents it.

## 5. Open decisions (resolved under autonomy)

1. `budget.max_calls` = SQL executions per item via the gated callback (documented).
2. Traces carry no timing; manifest carries aggregates (byte-reproducibility wins).
3. Provider adapters use httpx directly; SDK extras remain optional for users.
4. Smoke items carry literal `gold_value`s (the recipe-driven bank is Phase 5).
