# Phase 2 Briefing — Contracts and scorer core

Status: approved 2026-06-12 (pre-approved by Kartikeya; briefing delivered with the build).
Depends on Phase 0; consumes nothing from Phase 1 at runtime (the scorer is pure).

**Objective:** freeze the data contracts (Item, AgentRequest, AgentResponse, Verdict,
RunManifest); build the deterministic scorer for axes 1 (definitional), 3 (ambiguity),
4 (refusal) and the weighted aggregate; establish the golden suite that validates the
validator. No LLM anywhere — keys are not used in this phase.

## 1. Concepts (theory level)

- **Measurement theory & construct validity.** A benchmark is a measurement instrument: it
  must measure the construct it claims (business-correctness), reliably. Phase 2 is where
  the instrument's *scale* is defined: what counts as a pass, per axis, mechanically. Every
  judgment call (tolerance, exact counts, what happens at gold = 0) is written down and
  configurable rather than implicit — because an undocumented default silently becomes part
  of the construct.
- **Who validates the validator?** The scorer is the part everyone must trust, so it gets the
  strongest tests in the repo: a hand-verified golden suite (every case worked out by hand,
  committed as data) plus property-based tests (reconciliation is scale-invariant, tolerance
  is monotonic, the aggregate is bounded in [0,1]). The golden suite is the concrete answer
  to the circularity objection.
- **Purity as a testability strategy.** Scorer functions do no I/O, hold no globals, and read
  no clock: same inputs, same verdict, forever. Purity is what makes 100% branch coverage
  meaningful and lets old runs be re-scored from traces (Phase 8 proves auditability this way).
- **Untrusted input discipline.** Agent output is adversarial data. Anything malformed —
  bad JSON, a missing field, a clarify with no question — scores zero on all axes for that
  item and *records why*; the scorer never raises on agent input. (Raising is reserved for
  *our* mistakes: a non-finite gold value or a misconfigured item is a bug, not a score.)
- **Fail-closed scoring.** `unknown` counts against the agent in axis rates (it is not
  silently dropped), and `n/a` axes are excluded with weight renormalization. Both choices
  are printed in the report so nobody discovers them in the source.

## 2. Design (architecture level)

- **Contracts are the dependency sink.** All five models live in `contracts/`, frozen
  pydantic v2; the scorer imports contracts, never the reverse. JSON Schemas are exported to
  `docs/contracts/` by a script and a golden test asserts the committed schemas match a fresh
  export (so contract drift cannot be silent). After this phase, contract changes require an
  ADR + schema re-export + version bump.
- **Strict out, lenient in.** `AgentRequest` (we produce it) forbids unknown fields.
  `AgentResponse` (they produce it) ignores extra fields but is strict on types and on
  action-specific requirements: `answer` needs `value` + `sql`, `clarify` needs
  `clarifying_question`, `refuse` needs `refusal_reason`. `parse_agent_response` returns
  `AgentResponse | MalformedResponse` — it never raises.
- **Scoring rules (ADR-0003):** relative tolerance, default 0.5%, per-item override;
  `count` metrics match exactly; gold = 0 requires exactly 0 (relative tolerance is
  undefined at zero; fail closed). Clarifications must reference the actual ambiguous term;
  refusals must name the missing dimension; refusing a control is the over-refusal penalty.
- **Enforcement of the coverage gate:** a dedicated `make cov-core` target (wired into
  `check` and CI) runs the scorer tests with `--cov-fail-under=100` on exactly
  `reconcile`, `actions`, `aggregate` — the per-module gate ADR-0001 deferred.

## 3. Walkthrough (code level)

- `contracts/item.py` — `Item` + `GoldRecipe`. Validators enforce taxonomy coherence
  (trap class ↔ expected action), exactly one gold source for answer items, and that
  ambiguity/refusal items carry `ambiguous_term` / `missing_dimension` (these two fields are
  additions to the §10 sketch — required so "must reference the actual term" is mechanically
  checkable; recorded in ADR-0003).
- `contracts/agent_io.py` — `AgentRequest`, `Budget`, `AgentResponse`, `MalformedResponse`,
  `parse_agent_response`.
- `contracts/verdict.py` — `Axis`, `AxisStatus` (`pass|fail|na|unknown`), `AxisResult`
  (status + JSON evidence), `Verdict` (item id, per-axis results, roll-up).
- `contracts/manifest.py` — `RunManifest` + `RunTotals`; timezone-aware timestamp enforced.
- `contracts/export.py` + `scripts/export_schemas.py` — deterministic schema export
  (sorted keys), golden-tested.
- `scorer/reconcile.py` — `reconcile(agent_value, gold_value, value_type, tolerance)`.
- `scorer/actions.py` — `score_action(expected, response, ambiguous_term, missing_dimension)`
  covering the full 3×4 matrix (answer/clarify/refuse × answer/clarify/refuse/malformed).
- `scorer/aggregate.py` — `roll_up_item` (fail > unknown > pass > na) and
  `aggregate(verdicts, weights)` → per-axis rates + weighted overall in [0,1]; weights
  validated and echoed in the output.
- Tests: `tests/golden/scorer/` with hand-verified YAML fixtures (≥25 enforced by a count
  assertion) + property tests + contract unit tests.
- Alternatives considered: exceptions for malformed input (rejected: scorer must never raise
  on agent data); absolute tolerance (rejected: not scale-free; relative + per-item override
  wins); storing the aggregate weights in code (rejected: config + echoed in output).

## 4. Red-team summary (§13)

- **SW Engineer:** boundary cases (exactly-at-tolerance, gold=0, NaN/inf) are each a named
  golden fixture; hypothesis fuzzes the parser so no payload can raise.
- **Staff Engineer:** purity + contracts-as-sink is the leverage; the freeze makes later churn
  expensive on purpose (that is the point of this phase).
- **Solutions Architect:** JSON Schemas exported so third-party adapters can validate without
  importing Python.
- **Product Engineer:** evidence dicts are written for the failure gallery — every fail
  explains itself (numbers compared, term not referenced, over-refusal flag).
- **DevOps:** the 100%-branch gate runs as its own named CI step, so a regression points at
  the exact module; scoring 1000 verdicts must stay under 1s (it is arithmetic; verified).
- **Security Engineer:** agent output treated as untrusted data; no eval, no dynamic imports,
  no SQL execution anywhere in this phase.
- **End User:** weights, tolerance, and the fail-closed rules are printed with results, not
  buried in source.
- **Failure mode that matters most:** a wrong tolerance default poisons every later result —
  mitigated by configurability per item, ADR-0003 documentation, and an explicit revisit
  after the first real runs (register RT-011).

## 5. Open decisions

Pre-approved ("do what you think is best"); the calls made, on the record:
1. `unknown` counts against the rate (fail-closed) and `na` renormalizes — printed in output.
2. `AgentResponse` ignores extra fields; strict on types and action-specific requirements.
3. gold = 0 → exact match required (documented in ADR-0003).
4. `ambiguous_term` / `missing_dimension` added to Item (mechanical term-matching needs them).
5. CI actions bumped (checkout@v5, setup-python@v6) to clear the Node 20 deprecation warning.
