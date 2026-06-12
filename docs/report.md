# LedgerBench: measuring whether analytics agents are business-correct

*Technical report, v1.1 — June 2026. Kartikeya Mandhar.*
*Every figure traces to a committed run manifest under `benchmark/results/`.*

## 1. Motivation

An AI analyst can write SQL that parses, executes, and returns a confident number that
is wrong for the business: the wrong metric definition, silent double-counting through
a fan-out join, a specific answer to an ambiguous question, an invented answer to an
unanswerable one, or an explanation that does not match the query it ran. Execution
benchmarks (Spider, BIRD) score whether queries run and match a reference — a measure
that is saturating and that never asked the harder question. LedgerBench asks it:
**when the query runs fine, is the answer right?**

The bundled demonstration makes the gap concrete. A deterministic keyword baseline
("naive") run over the public bank executes successfully on **100%** of its attempts
and is business-correct on **9.3%** of items (manifests:
`benchmark/results/naive-{closed,open}/`). Execution success and business correctness
are different quantities. The benchmark measures the distance between them for real
agents in two conditions: **closed book** (schema only) and **open book** (schema plus
the encoded business rulebook). The hypothesis: the rulebook narrows the gap but a
residual survives. The keyed runs confirm it: gpt-4o-mini improves from **42.0% to
59.3%** business-correct when handed the rulebook — and still gets **two answers in
five wrong** while executing flawlessly. Documentation helps; it does not verify.

## 2. The trap taxonomy

150 public items over two deterministic worlds (a SaaS company and a finance ledger),
each item engineered to trigger exactly one failure class:

| class | n | expected behavior | the trap |
|---|---|---|---|
| definitional | 40 | answer | naive readings miss declared filters/exclusions (refunds; void/pending) |
| grain / fan-out | 30 | answer | the question invites a 1:N join that multiplies the measure |
| ambiguity | 25 | clarify, naming the term | the rulebook declares two defensible readings |
| refusal | 20 | refuse, naming the dimension | the dimension is plausible but absent from the schema |
| period / tz / fiscal | 15 | answer | UTC storage vs reporting timezone; February fiscal year |
| controls | 20 | answer | none — refusing one is the over-refusal penalty |

Controls price in gaming: an agent cannot win by refusing or hedging everything. A
30-item private split (same construction, separate private repository) detects
contamination; its results are only ever published as aggregates.

## 3. Method

**Ground truth by construction.** Each world is generated from an explicit seed
(byte-reproducible, content-digested) and governed by a rulebook: declared metric
definitions, exclusions, grains, relationship cardinalities, fiscal calendar,
timezones. Items carry gold *recipes* (a rulebook metric id plus an optional window),
never baked values: gold is compiled to SQL and executed against the world at
validation and scoring time. No model is involved in gold, and disagreement with a gold
value is disagreement with a public, versioned, mechanical rulebook — not with an
author's reading. The CI linter recomputes all 105 recipe golds on every run.

**Five axes, scored independently.**
1. *Definitional*: numeric reconciliation to gold — relative tolerance 0.5% (per-item
   override), integer counts exact, gold of zero requires zero (ADR-0003).
2. *Grain safety*: static analysis of the agent's SQL. Join edges are oriented one→many
   from declared cardinalities; a source's rows are duplicated iff a walk away from it
   crosses a one→many edge — one rule that catches fan traps, chasm traps, and dimension
   measures summed across fact joins, while star rollups stay clean. Fail closed: out of
   fence → `unknown`, never a guess. Measured on the 47-query labeled corpus:
   **TPR 1.000, FPR 0.000, unknown rate 0.255** (printed by the test suite every run).
3. *Ambiguity*: the agent must clarify, and the clarification must reference the actual
   ambiguous term — generic hedging fails.
4. *Refusal*: the agent must refuse, naming the missing dimension; refusing answerable
   items is penalized via the controls.
5. *Faithfulness*: deterministic extraction of tables/joins/filters/exclusions/date
   bounds from the SQL; an LLM judge confined to semantic matching only, double-run at
   temperature 0, disagreements surfaced as `unknown`, calls cached, prompt versioned.
   Live calibration: **0.90 agreement** on the 20-case hand-labeled set (gate ≥ 0.8;
   `scripts/judge_calibration.py`), measured 2026-06-12.

**Safety and reproducibility.** Every model-generated statement passes a SELECT-only
gate (parse → single statement → structural denylist → comments stripped) and runs on
read-only, time- and row-capped connections; 30 malicious fixtures assert both
rejection and zero executions. Traces contain no wall-clock; a same-seed offline rerun
is byte-identical. Scoring is a pure replay over traces: re-scoring an old run under
new tolerances costs zero model calls (verified by the `ledgerbench report` path).

## 4. Results

**The floor (committed).** The naive baseline over the public 150, three seeds:

| agent | condition | ran fine | business-correct | weighted overall |
|---|---|---|---|---|
| naive | closed book | 100% | 9.3% | 48.9% |
| naive | open book | 100% | 9.3% | 48.9% |

Three observations the floor already supports. (1) The headline gap is real and large:
every query executed; one in eleven answers was right. (2) The identical closed/open
scores show the floor ignores documentation entirely — providing the rulebook helps
only an agent that reads it. (3) The per-axis profile is diagnostic: the baseline
passes most grain checks (its single-table templates cannot fan out) while failing
definitional reconciliation and every behavioral axis — different failure modes are
genuinely different measurements.

**Keyed agents (committed).** Run within a deliberately small credit budget
(total model spend across all runs: **$1.62**), with per-run hard caps:

| agent | condition | seeds | ran fine | business-correct | weighted overall |
|---|---|---|---|---|---|
| gpt-4o-mini | closed | 11, 22, 33 | 100% | **42.0%** | 59.9% |
| gpt-4o-mini | open | 11, 22, 33 | 100% | **59.3%** | 58.7% |
| claude-haiku-4-5 | closed | 11 | 100% | **38.0%** | 45.4% |
| claude-haiku-4-5 | open | 11 | 100% | **44.0%** | 29.1% |

**The A/B finding.** The rulebook narrows the gap for both models (mini +17.3 points;
haiku +6.0) and closes it for neither: open-book mini is still wrong on 40.7% of items
that all executed cleanly. The residual is the benchmark's argument: encoding semantics
into documentation helps agents that read it, and is not a substitute for verification.

**Documentation has side effects.** mini's per-axis profile shifts asymmetrically with
the rulebook: definitional (0.46→0.57) and ambiguity (0.00→0.29) improve, while grain
safety (0.94→0.79), refusal (0.90→0.78), and faithfulness (0.61→0.40) *degrade* — the
rulebook emboldens the model to join more aggressively, answer questions it should
refuse, and claim more than its SQL does.

**The contract binds, and that is a result.** Open-book haiku produced rulebook-correct
SQL (right filters, right exclusions) on 67 items but returned `value: null` — it knew
the definition and skipped computing the number, so 46% of its open-book responses
scored zero as malformed (the contract requires a value with every answer). Its
weighted overall collapses (45.4→29.1) even as its well-formed answers improved enough
to lift business-correct (38→44%). An analyst who hands you perfect SQL and no number
has not answered the question; agents are scored on delivery, not intent (RT-008). The
v1 adapter prompt described `value` as "number or null", which invited the behavior; it
is tightened in this release, and reruns under the tightened prompt are future work.

**Seeds and nondeterminism.** mini ran 3 seeds: 29–41% of items vary at the response
level across seeds at temperature 0, but aggregate business-correct varies by only
0.7 points (closed) / 3.3 points (open). haiku ran a single seed due to credit limits;
its aggregates carry uncertainty on that order. Confidence-vs-accuracy calibration
curves from the recorded `confidence` field are deferred with the larger-model runs.

## 5. Failure gallery (floor run, verbatim from traces)

1. **Fan-out temptation resisted by accident** (`saas-grain-001`): asked for revenue
   from shipped orders, the baseline summed all orders single-table — wrong value
   (definitional fail) but grain-safe SQL (grain pass). The axes separate the errors.
2. **Ambiguity answered** (`saas-amb-001`, "How many active users do we have?"): the
   baseline counted rows of `customers` — confident, executable, and meaningless given
   two declared definitions (7-day and 30-day). Ambiguity axis: fail.
3. **The unanswerable answered** (`saas-ref-001`, "revenue by acquisition channel"):
   no such dimension exists anywhere in the schema; the baseline returned a number
   anyway. Refusal axis: fail, with the missing dimension named in evidence.

## 6. Limitations

- **Item count and domain breadth**: 150 public items over two synthetic worlds;
  DuckDB dialect only in v1. Real warehouses and dialects differ (the BYO mode and the
  Snowflake seam are the path, not a claim).
- **The grain checker is deliberately incomplete**: a quarter of corpus queries land in
  `unknown` by fence design. We publish TPR/FPR/unknown rather than pretending
  completeness; `unknown` is never folded into `safe`.
- **The judge is confined but still a model**: one axis, double-run, cached, versioned,
  calibration-gated — and excluded from gates entirely when not configured.
- **Small-model, small-budget tier**: the keyed runs cover gpt-4o-mini and
  claude-haiku-4-5 under a few dollars of credit (haiku: one seed). Larger models
  (claude-sonnet-4-6, gpt-4o) remain on the punch list; nothing about them is projected.
- **Adapter prompt v1 permitted `value: null`**: haiku exploited it open-book (scored
  per contract; analyzed above). The prompt is tightened going forward; cross-prompt
  comparisons are not made.
- **Author-written items**: mitigated by mechanical gold, the linter, and the planned
  external practitioner review pass (open item on the launch punch list).

## 7. Future work

Snowflake execution adapter; MetricFlow ingestion for projects with native semantic
models; deeper grain-checker fence with corpus-gated extensions; bank rotation (v2)
with private-split promotion; a GitHub Action wrapping the threshold gate; community
adapters via the entry-point group.

## Appendix: reproducing

```bash
pip install -e . && ledgerbench demo            # the gap, locally, ~35s, no keys
ledgerbench validate                            # re-lint the bank, recompute gold
python scripts/run_benchmark.py benchmark/results   # the committed runs (naive tier)
python scripts/build_leaderboard.py             # regenerate the leaderboard page
```

Every leaderboard number traces to `benchmark/results/<agent>-<condition>/manifest.json`.
