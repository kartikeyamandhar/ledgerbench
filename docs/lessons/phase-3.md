# Lessons — Phase 3 (Static grain checker)

## What worked

Probing sqlglot's actual AST and Scope API empirically *before* designing (a 20-line
script) prevented building on a wrong assumption — naive `find_all(Table)` provably
mis-resolves CTE names as base tables, which would have been a silent correctness bug.
The labeled corpus as the spec worked exactly as intended: when the first full run
failed one case, the failure was a display-orientation nit, not a verdict error, and
the fix was confined and visible. Printing TPR/FPR/unknown-rate in test output makes
the checker's honesty self-documenting in every CI log.

## What was harder than expected

The fan-out rule itself. The obvious formulation ("mark the one-side of each 1:N
edge") passes the canonical fan trap but *misses chasm traps entirely* and mishandles
snowflake rollups — discovered by hand-tracing `customers⋈orders⋈subscriptions`
during design, before any code. The correct rule (a source is duplicated iff a BFS
away from it crosses an edge in the one→many direction) is simpler than the patched-up
wrong one, but finding it took most of the phase's thinking time. Lesson: for
correctness-critical logic, hand-verify the rule on adversarial examples before
implementing; the implementation was then right on the first run (18/18 design cases).

## What I would do differently

Write the corpus *before* the checker next time, not alongside it — it was the design
tool anyway, and starting from labeled queries would have surfaced the chasm
counterexample even earlier. Also: decide evidence display conventions (one→many
orientation) up front; the only test failure of the phase was that.

## Carry-forward action

- The `unknown` rate (0.255 on the corpus) is the price of the fence; Phase 6's report
  must surface unknowns honestly, and post-launch fence-widening (deeper nesting,
  Snowflake) must arrive with corpus rows (RT-002, RT-012).
- Phase 5's grain trap items must stay inside the supported fence so the checker can
  actually adjudicate them — check items against `check_grain` in the linter.
- `grain_axis_result` is ready for the Phase 6 wiring; no scorer changes needed.
