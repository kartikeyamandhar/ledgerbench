# LedgerBench: measuring whether analytics agents are business-correct

*Technical report, v1.0 — June 2026. Kartikeya Mandhar.*
*Sections marked **[pending keyed runs]** await the frontier-agent benchmark; no number
in this report is projected — every published figure traces to a committed run manifest.*

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
are different quantities. The benchmark exists to measure the distance between them for
real agents, in two conditions: **closed book** (schema only) and **open book** (schema
plus the encoded business rulebook). The hypothesis: the rulebook narrows the gap but a
residual survives — which is the argument for verification infrastructure beyond
documentation. **[pending keyed runs]** for the frontier A/B delta.

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
   **[pending keyed runs]** for live judge calibration (gate: agreement ≥ 0.8 on the
   20-case hand-labeled set; `scripts/judge_calibration.py`).

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

**Frontier agents.** **[pending keyed runs]** — 4–6 configurations (Anthropic, OpenAI
APIs; plus the committed floor) × 2 conditions × 3 seeds; per-axis results, the
closed-vs-open delta, and confidence-vs-accuracy calibration curves computed from the
`confidence` field already captured in every trace. Total spend is hard-capped at $150
by the budget module.

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
- **Floor-only results at publication**: frontier rows land when keyed runs execute;
  nothing here projects them.
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
