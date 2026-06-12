# Phase 5 Briefing — Item bank and faithfulness judge

Status: proceeding under standing autonomy grant (2026-06-12); briefing delivered with the build.
Depends on Phases 1 (worlds), 2 (contracts), 4 (runner) — all complete.

**Objective:** author the 150 public items (taxonomy-exact), build the linter that keeps
the bank honest in CI (including full gold recomputation from the rulebook), and complete
the fifth axis (explanation faithfulness) with the judge confined, double-run, and cached.

## 1. Concepts (theory level)

- **Items as recipes, not baked values.** An answer item carries a `gold_recipe`
  (rulebook metric id + params), never a precomputed number. Gold is *derived* at
  validation/run time by compiling the recipe against the built world. Consequences:
  a world regeneration or tolerance change re-derives gold consistently; items are
  seed-independent; and the anti-subjectivity argument is mechanical — gold comes from
  the declared rulebook, not the author's opinion. This is the exact mechanism BYO mode
  (Phase 7) uses, proven here first.
- **Adversarial behavioral testing.** Each trap class targets one failure mode, and the
  *expected behavior* differs by class: definitional/grain/period/control items must be
  answered; ambiguity items must be clarified (naming the term); refusal items must be
  refused (naming the missing dimension). Controls exist so refusing everything cannot
  win (over-refusal penalty, Phase 2).
- **Goodhart and contamination.** A public bank will be memorized eventually. Defenses:
  the 30-item private split (separate repo, never referenced here), bank versioning
  (`public_v1` is append-only; corrections ship as v1.1), and the controls that price in
  gaming. The linter is the gate that makes community additions safe later.
- **Judge confinement (RT-003).** Faithfulness is the only axis allowed an LLM judge,
  and only for the *semantic match* step: "does this stated assumption match these
  extracted SQL facts?". Everything extractable deterministically (tables, predicates,
  date ranges, exclusions) is extracted deterministically with sqlglot. The judge is
  double-run at temperature 0; disagreement is flagged `unknown`, never averaged; calls
  are cached by content hash; the prompt is versioned in the repo.

## 2. Design (architecture level)

- **`gold/compiler.py`:** `compile_recipe(definition, params, reference_date) -> SQL`
  and `compute_gold(con, ...) -> float`. The SQL shape is mechanical:
  `SELECT <measure> FROM <base_table> WHERE <filters> AND NOT (<exclusions>) AND
  <params.extra_where>`. The `reference_date` token in rulebook filters is substituted
  from the rulebook's declared reference date. The params vocabulary is deliberately
  tiny in v1 — `extra_where: list[str]` — and every compiled query passes the same
  `vet_sql` gate as agent SQL (defense in depth applies to our own queries too).
- **The bank:** `benchmark/items/public_v1.jsonl`, 150 items, taxonomy-exact
  (definitional 40, grain 30, ambiguity 25, refusal 20, period 15, control 20), spread
  across both worlds, ids `<world>-<class>-NNN`, version `public_v1`, append-only.
- **The linter (`validate_items`)**: unique ids; schema-valid; taxonomy counts exact;
  every ambiguity term/refusal dimension exists in its world's rulebook (preconditions);
  no item references the other world; every answer item's recipe compiles, passes the
  gate, executes against a freshly built world, and yields a finite value (integral for
  counts); grain items declare their grain. Runs in CI via the test suite (and is the
  engine behind the `ledgerbench validate` CLI, wired fully in Phase 6).
- **`scorer/faithfulness.py`:** `extract_sql_facts(sql)` (sqlglot: tables, joins,
  filters, exclusions/negations, date bounds, aggregates — deterministic, no model) →
  `score_faithfulness(response, facts, judge, cache)`. Judge protocol is an injected
  callable; `CachingJudge` wraps any judge with a sha256 content-hash cache;
  `AnthropicJudge` (httpx, temp 0) exists for the live pass; tests use scripted judges.
  Axis semantics: no assumptions → `na` (the judge never runs — cost control); any
  assumption contradicted → `fail` naming it; double-run disagreement → `unknown`;
  otherwise `pass`.
- **Calibration set:** 20 hand-labeled cases (`tests/golden/faithfulness/`). CI uses
  them to pin extractor behavior and judge plumbing with scripted judges. The *live*
  judge-agreement measurement (gate ≥ 0.8) requires an API key: it ships as
  `scripts/judge_calibration.py` and is an explicit pre-launch punch-list step.
- **Private split:** protocol documented in `docs/private-split.md` (separate
  `ledgerbench-private` repo, 30 items, same linter, only aggregates ever published).

## 3. Walkthrough (code level)

New/changed: `gold/compiler.py`; `generator/suite.py` gains the bank loader/validator
(`load_bank`, `validate_items` — the generator package is its natural home and Phase 7
extends it); `scorer/faithfulness.py`; `benchmark/items/public_v1.jsonl`;
`tests/unit/test_gold_compiler.py`, `tests/unit/test_faithfulness.py`,
`tests/golden/faithfulness/calibration.yaml` (+ test), `tests/integration/test_item_bank.py`
(the linter in CI, including gold recomputation against freshly built worlds);
`docs/private-split.md`; `benchmark/items/README.md` (taxonomy + authoring guide +
anti-subjectivity argument).

**Alternatives considered:** baked gold values (rejected: silently drift from worlds;
recipes re-derive); LLM-phrased questions (rejected for v1: §17 forbids LLM in
generation; phrasing variety is hand-authored); judge as a third vote on disagreement
(rejected: RT-003 says flag, not arbitrate — disagreement is signal, surfaced in the
report); free-form params in recipes (rejected: `extra_where` only, keeps gold auditable).

## 4. Red-team summary (§13)

- **SW Engineer:** the linter is executable spec; every bank edit must pass gold
  recomputation in CI. Extractors are pure sqlglot walks with fixture tests.
- **Staff Engineer:** `load_bank`/`validate_items` in `generator/` is the seam Phase 7
  reuses for generated suites; the compiler is the same one BYO gold uses.
- **Solutions Architect:** recipes executing through `vet_sql` means BYO gold
  computation inherits the same safety posture as agent SQL.
- **Product Engineer:** rubrics are written so a stranger could grade by hand; failure
  gallery quality in Phase 6 depends on them.
- **DevOps:** full-bank gold recomputation must stay under 5 minutes in CI (it is ~130
  scalar aggregates over 100k-row worlds; measured in the integration test).
- **Security Engineer:** judge prompts contain no secrets; cache lives in the local
  filesystem only; compiled gold SQL passes the gate.
- **End User:** every item explains itself: question, rubric, recipe — nothing hidden.
- **Failure modes:** author bias in ambiguity items (mitigated: only planted, rulebook-
  declared ambiguous terms are used; both readings exist as metrics); judge cost
  (mitigated: judge only runs on non-empty assumptions, cached by hash, double-run is
  2 calls not N); contamination (private split + versioning; RT-004).
- **Register adds: RT-014** — calibration agreement gate (≥0.8) cannot run keyless in
  CI; risk of shipping an uncalibrated judge; mitigated: scripted-judge plumbing tests
  in CI + a mandatory pre-launch live calibration step on the punch list.

## 5. Open decisions (resolved under autonomy)

1. Recipe params = `extra_where` only; anything richer waits for real demand.
2. Item ids: `<world>-<class abbrev>-NNN` (e.g. `saas-def-001`, `fin-amb-007`).
3. The 25 ambiguity items split over the two planted terms (active users / revenue);
   the 20 refusal items over the two planted absent dimensions — preconditions only,
   no invented ambiguity (that is the anti-subjectivity line).
4. Judge = Anthropic (haiku-class, temp 0) when live; injected/scripted in all tests.
5. `validate` CLI subcommand lands now (thin shell over `validate_items`); full CLI
   assembly remains Phase 6.
