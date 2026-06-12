# Data contracts reference

Frozen as of Phase 2 (v0.2.0). Changes require an ADR, a JSON Schema re-export
(`make schemas`), and a minor version bump; a golden test fails CI if the committed
schemas under [`docs/contracts/`](contracts/) drift from the models in
`ledgerbench.contracts`. The scoring rules these contracts feed are in
[ADR-0003](decisions/ADR-0003.md).

## The five contracts

**Item** — one benchmark question: `id`, `world`, `question`, `trap_class`
(`definitional | grain | ambiguity | refusal | period | control`), `expected_action`,
exactly one of `gold_recipe` (rulebook metric id + params, re-derivable) or `gold_value`,
`declared_grain`, `tolerance_override`, `ambiguous_term` (ambiguity items),
`missing_dimension` (refusal items), `rubric`, `version`. Validators enforce taxonomy
coherence at load time (e.g. an ambiguity item must expect `clarify` and carry its term).

**AgentRequest** (runner → adapter) — `item_id`, `question`, `schema_ddl`, `context_pack`
(null in the closed-book condition), `dialect` (`duckdb`), `budget` (`max_calls`,
`timeout_s`). Strict: unknown fields are forbidden (we produce this; extras are bugs).

**AgentResponse** (adapter → runner) — `action` (`answer | clarify | refuse`), `value`,
`sql`, `assumptions`, `clarifying_question`, `refusal_reason`, `confidence` (0–1).
Lenient on extras (ignored), strict on substance: `answer` requires `value` + `sql`,
`clarify` requires `clarifying_question`, `refuse` requires `refusal_reason`. Anything
else is malformed and **scores zero on every axis for that item** —
`parse_agent_response` returns the reason and never raises.

**Verdict** (scorer output per item) — per-axis `AxisResult` with status
`pass | fail | na | unknown` and JSON evidence (the numbers compared, the unreferenced
term, the over-refusal flag), plus the item roll-up (fail > unknown > pass > na).
Fail-closed: `unknown` counts against the agent; `na` renormalizes.

**RunManifest** — the reproducibility record: tool version, suite version + hash, world
content digests, agent id, model snapshot id, condition (`closed | open`), seeds,
repetitions, totals (items, cost USD, latency p50/p95), git commit, timezone-aware
timestamp. Every published number must trace back to one of these.

## JSON Schemas

Machine-readable schemas for all five live in [`docs/contracts/`](contracts/) — adapter
authors can validate against `AgentResponse.json` without importing Python.
