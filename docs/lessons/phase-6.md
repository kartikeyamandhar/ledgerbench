# Lessons — Phase 6 (CLI, reporter, demo)

## What worked

The demo landed on the first full run and produced the project's headline finding live:
the naive baseline's queries ran fine 100% of the time and were business-correct 9% of
the time, in 35 seconds, offline. Everything assembled rather than being built: traces
from Phase 4, gold from Phase 5, axes from Phases 2–3 — the pipeline module is 180 lines
of wiring. Server-side SVG was the right call: the report renders with JavaScript
disabled, embeds everything, and stays ~150 KiB for 150 items.

## What was harder than expected

One real scoring-semantics bug surfaced only when the full demo ran: with no judge
configured, faithfulness scored `unknown`, and `unknown` poisons the item roll-up by
design — so business-correct read 0% when the truth was 9%. The fix distinguishes
*tool-side non-evaluation* (`na`, "not evaluated", excluded from gates) from
*agent-caused unknowns* (which rightly count against). The lesson generalizes: every
`unknown` needs an owner — the agent or the tool — and the two must never be conflated
in aggregates. RT-015 now records this.

## What I would do differently

Run the end-to-end demo earlier in the phase, before the unit tests were complete — the
roll-up bug was invisible at unit scope and obvious at system scope. The exit-code
matrix as integration tests (not docs) was worth it immediately: the bad-config path had
a wrong error message that a test caught.

## Carry-forward action

- README screenshot still pending (needs a browser) — punch list.
- The 5-minute demo claim is comfortably met (~35 s); recorded in README with the
  measured numbers.
- Phase 8's calibration curves can be computed from `confidence` already captured in
  traces; no contract change needed.
