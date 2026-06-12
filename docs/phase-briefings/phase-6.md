# Phase 6 Briefing — CLI, reporter, demo end-to-end

Status: proceeding under standing autonomy grant (2026-06-12); briefing delivered with the build.
Depends on Phases 3, 4, 5 — all complete. The End User persona leads this review.

**Objective:** assemble the pieces into the five-minute experience: `pip install`,
`ledgerbench demo`, a rendered single-file report that a data lead understands without
reading the source. This phase also wires the five axes into one scoring pipeline over
traces — the seam every later re-scoring uses.

## 1. Concepts (theory level)

- **The product moment.** Infrastructure earns nothing until the demo lands. The bar:
  no API keys, no network, under five minutes, one HTML file at the end that explains
  *the finding* — execution success ≠ business correctness — with the evidence attached.
- **Traces → verdicts as a pure replay.** Scoring consumes only what Phase 4 traced and
  what the worlds/rulebooks declare. Nothing about scoring calls a model (the judge is
  optional and injected). Re-render and re-score are the same act over the same files —
  which is what makes results auditable after the fact.
- **Thresholds as a contract.** `ledgerbench.yaml` axis thresholds turn the report into
  a CI gate: exit code 0 = all axes at or above threshold, 1 = breach (the failing axes
  named on stderr), 2 = usage/config error. A benchmark you can put in CI is a tool, not
  a paper.
- **Honest rendering.** The report prints the weights, the unknown rates, and the
  manifest (suite hash, world digests, seeds, model snapshot) in the footer. No number
  appears without its provenance; `unknown` is never folded into `pass`.

## 2. Design (architecture level)

- **`scorer/pipeline.py` (addition to the §9 tree, documented here like `worlds.py` was
  in ADR-0002):** `score_trace(item, record, *, grain_model, registry, con, judge=None)
  -> Verdict` — axis 1 reconcile (gold computed live from the item's recipe against the
  world connection), axis 2 `check_grain` on the answer SQL, axes 3–4 `score_action`,
  axis 5 `score_faithfulness` when a judge is configured else `unknown` with the reason
  "no judge configured" (the offline demo says so honestly rather than pretending).
  Plus `score_run(items, traces, ...) -> list[Verdict]`.
- **`config.py`:** pydantic model of `ledgerbench.yaml` (suite, world seed, agent,
  conditions, seeds, budget, tolerances, weights, thresholds, report path); validated
  loud, defaults match `ledgerbench.example.yaml`.
- **`report/`:** `charts.py` renders inline SVG server-side (no JS, no CDN — the report
  renders with JavaScript disabled by construction); `html.py` fills
  `templates/report.html.j2` (Jinja2 autoescape ON; agent SQL is escaped text — XSS-safe).
  Sections: headline bars (ran-fine vs business-correct), per-axis breakdown with
  unknown rates, closed-vs-open comparison when both conditions are present, failure
  gallery (question, agent SQL, gold SQL, evidence) as `<details>` elements (collapsible
  without JS), manifest + weights footer. Single file, target < 2 MB.
- **`cli.py` complete:** `demo` (build worlds → run naive open-book over the public
  bank → score → render → open), `run` (config-driven, closed/open conditions),
  `report` (re-render from traces + manifest), existing `world build` and `validate`.
  Every command's `--help` written for a stranger; every error names the next step.
  `demo --limit N` keeps CI fast and is honest UX (full bank by default).
- **Performance:** demo < 5 min on a laptop (worlds ~40 s + naive run seconds + 150
  gold computations ~instant + render < 5 s). **Security:** no network anywhere in
  `demo`; report embeds everything inline.

## 3. Walkthrough (code level)

New: `scorer/pipeline.py`, `config.py` body, `report/charts.py`, `report/html.py`,
`report/templates/report.html.j2`, `cli.py` (demo/run/report commands).
Tests: CLI integration via typer's runner (demo with `--limit`, exit-code matrix
0/1/2, report re-render); golden-render snapshot (fixture verdicts → template → key
strings asserted); pipeline unit tests (each axis wired, judge-absent path, malformed
trace → all-axes fail with reason); README quickstart finalized (screenshot is a
pre-launch punch-list item — needs a browser).

**Alternatives considered:** client-side JS charts (rejected: CDN/no-JS constraints;
SVG is sufficient and renders everywhere); a JSON report (deferred post-launch, noted
in §future); scoring inside the executor (rejected long ago: traces are the interface);
matplotlib for charts (rejected: heavy dependency for four bar groups).

## 4. Red-team summary (§13)

- **End User (lead):** the report must answer "would I trust this agent?" in one
  scroll: headline gap, axis table with unknowns visible, failures with the actual SQL.
  Jargon in evidence strings is rewritten for the gallery.
- **Product Engineer:** zero-key demo; `--limit` for impatient first runs; every CLI
  error message says what to do next.
- **SW Engineer:** the pipeline is pure given its inputs; exit-code matrix is an
  integration test, not a docstring promise.
- **Staff Engineer:** CLI stays a thin shell — everything importable; `score_run` is
  the API notebooks will use.
- **Solutions Architect:** thresholds make it a CI gate today; the JSON report (post-
  launch) is the machine-consumption seam.
- **DevOps:** the timed demo test runs in CI with `--limit 30` (the 5-minute claim is
  asserted on the full bank locally before launch, recorded in docs).
- **Security Engineer:** autoescape on; agent SQL never interpolated raw; no network.
- **Failure modes:** report scope creep into a dashboard (fence: one template, one
  file, `<details>` is the only interactivity); demo slow on cold laptops (row caps
  from Phase 1 + measured timings printed).
- **Register add: RT-015** — offline demo scores faithfulness as `unknown` (no judge);
  risk of misreading the axis as failing; mitigated: the report labels it "not
  evaluated (no judge configured)" distinctly from agent-caused unknowns.

## 5. Open decisions (resolved under autonomy)

1. `scorer/pipeline.py` added to the tree (documented here; same precedent as
   `worlds.py`).
2. Judge absent → faithfulness `unknown` with an explicit non-agent reason, rendered
   as "not evaluated" in the report (RT-015).
3. Charts are server-side inline SVG; no JS anywhere in the report.
4. `demo --limit N` exists; default is the full bank.
5. README screenshot deferred to the pre-launch punch list (needs a browser).
