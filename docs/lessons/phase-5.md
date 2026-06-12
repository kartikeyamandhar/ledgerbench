# Lessons — Phase 5 (Item bank and faithfulness judge)

## What worked

Items-as-recipes carried the whole phase: because gold derives from the rulebook at
validation time, the 150-item bank needed zero baked numbers, the linter's "does every
gold recompute?" check is total (105/105 recipes execute), and the bank is
automatically consistent with any world seed. Constraining ambiguity items to
*declared* ambiguous terms and refusal items to *declared* absent dimensions made the
anti-subjectivity argument enforceable by the linter instead of aspirational. The
grain-item design (restrict-by-existence via `IN` subqueries) produced genuinely
well-posed traps whose gold cannot fan out by construction.

## What was harder than expected

Making finance definitional items non-ambiguous: "revenue" alone is the world's
planted ambiguous term, so every definitional question there had to name its reading
(net/gross/posted) without becoming a control. The line between
definitional/period/control is thinner than the taxonomy table suggests; the rubric
field is what keeps each item honest about which failure it tests. Also small but
real: sqlglot re-renders `DATE 'x'` as `CAST('x' AS DATE)`, which broke a too-literal
test — assert on meaning, not on surface form.

## What I would do differently

Author the calibration set *before* the faithfulness extractors — two cases forced
extractor changes (NEQ-as-exclusion, INTERVAL as a date bound) that would have been
free if the labels existed first. Same lesson as the grain corpus: data first.

## Carry-forward action

- **Punch list:** live judge calibration (`scripts/judge_calibration.py`, needs
  `ANTHROPIC_API_KEY`) must run before launch and the measured agreement recorded in
  docs (RT-014).
- Phase 6 wires `score_faithfulness` into the run pipeline with a `CachingJudge`
  (disk cache under `.ledgerbench/judge_cache/`); the naive/demo path needs no judge
  because the naive adapter states one fixed assumption — budget for judge cost only
  in live benchmark runs.
- The external practitioner review pass over the bank (RT-006) remains open and is
  on the punch list with the other key-gated steps.
