# Lessons — Phase 4 (Runner, adapters, safety)

## What worked

The audit-log design made the kill-tests assert what actually matters: not "an error
was raised" but "the statement never reached the engine" — `SafeExecutor.audit_log`
stays empty for every blocked fixture. Centralizing untrusted-input handling (adapters
return raw payloads; the executor parses once) kept the security boundary in two files
instead of five. Keeping wall-clock out of trace records made the byte-identical-rerun
acceptance criterion trivially true instead of a fight with timestamps.

## What was harder than expected

Real-world type edges, found by tests rather than foresight: DuckDB returns
`decimal.Decimal` for DECIMAL columns (the scalar-extraction check silently produced
`value=None` until a test caught it), and the naive adapter's schema regex broke on
single-line DDL because column splitting was line-based instead of paren-aware
comma-based. Also a design refinement mid-phase: a per-item call-cap breach should fail
*that item*, not abort the run — splitting `CallBudgetExceededError` out of
`BudgetExceededError` made the two blast radii explicit.

## What I would do differently

Decide the trace-volatility rule (no timing in traces; volatile data in the manifest)
before writing the executor rather than during — it forced a small rework. And start
with the comma-aware DDL splitter; "regex the schema" is always paren-blind on the
first try.

## Carry-forward action

- The smoke items carry literal `gold_value` placeholders; Phase 5 replaces this
  pattern with recipe-derived gold and the linter must reject placeholder-style items
  in the public bank.
- Provider adapters estimate cost from a small static price table; Phase 8 must
  document that estimates are estimates and the USD cap is the real rail.
- `sql_probe` is the documented adapter protocol; the faithfulness axis (Phase 5) can
  read `adapter_sql_calls` from traces as evidence of what the agent actually looked at.
