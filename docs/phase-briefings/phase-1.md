# Phase 1 Briefing — Worlds (the fake company)

Status: awaiting `approve phase 1`. Depends on Phase 0 (complete, v0.0.1).

**Objective:** two deterministic fake companies (`saas`, `finance`) whose data and rulebooks
contain *every precondition the trap taxonomy needs*. "Ground truth by construction" starts
here — Phase 1 builds the construction; gold derivation (Phase 5/7) consumes it. No scoring,
no agents, no gold compilation yet.

## 1. Concepts (theory level)

- **The oracle problem, and sidestepping it by construction.** Software testing's "oracle
  problem" is: to check an answer you must already know the correct one. For analytics the
  correct *business* answer is usually unknown or contested — which is the whole reason
  agents can be confidently wrong. We don't solve the oracle problem; we *dissolve* it by
  building a world whose semantics we *declare* (the rulebook) and from which the true
  answer is *derived mechanically*, never judged. Phase 1 lays that declared world.
- **Ground truth by construction & determinism.** Every world is generated from an explicit
  seed with no wall-clock, no network, no unordered iteration — so regeneration is
  *byte-identical*. That reproducibility is what lets a hash assert "this is the same world"
  and lets a published benchmark be re-run by anyone. Determinism here is not tidiness; it's
  the precondition for the benchmark being trustworthy.
- **Relational grain & the fan trap.** *Grain* = what one row represents. A one-to-many join
  multiplies rows; summing a measure that lives on the "one" side after such a join
  double-counts. Canonical example: a \$100 order joined to its 3 shipments becomes
  3 × \$100 = \$300 of "revenue." Phase 1 deliberately *plants* this precondition (orders
  one-to-many shipments, the revenue measure on orders) so Phase 3's static grain checker
  has a real trap to catch. (Its cousin, the *chasm trap*: two unrelated one-to-many paths
  from a shared dimension.)
- **The rulebook as canonical semantics — "the law."** Metric definitions, exclusions,
  grains, cardinalities, fiscal calendar, and timezones are declared once in YAML. Gold
  later derives from this mechanically. This is the project's anti-subjectivity move: a
  contested "what is revenue?" becomes a *declared* definition, and the benchmark measures
  the agent against the declaration, not against an opinion.
- **Construct validity = measurement preconditions.** To *measure* a failure class the world
  must *contain* the condition that triggers it: an ambiguity item needs a genuinely
  two-meanings term; a refusal item needs a plausible-but-absent dimension; a fan-out item
  needs a real one-to-many. The acceptance "checklist test" (every trap class has ≥1
  precondition in *each* world) is a construct-validity guard against shipping a benchmark
  that can't actually exercise what it claims.
- **Ecological validity vs verifiability (a designed tension).** A suspiciously clean
  warehouse isn't credible to a data lead; arbitrary mess makes gold uncomputable. Phase 1
  resolves this with *deliberate, documented* nulls and duplicates — every irregularity
  recorded in the rulebook so gold stays mechanically computable while the world still looks
  real.
- **Worlds are data, not code.** Downstream modules consume only the `DefinitionRegistry`
  and `GrainModel` abstractions, never raw YAML or raw tables — which is what lets BYO mode
  (Phase 7) swap the loader and change nothing else.

## 2. Design (architecture level)

- **The two canonical structures (the architectural spine of this phase):**
  - `DefinitionRegistry` — metric definitions: `id`, `base_table`, `measure` expression,
    `filters`, `exclusions`, `grain`, and a `value_type` (`numeric` vs `count`) that Phase 2
    reconciliation needs for the integer-exact-match rule.
  - `GrainModel` — `TableGrain` (table → grain columns) and `Relationship`
    (`from`/`to`/`cardinality`/join keys). Phase 3's checker queries this for cardinalities.
  Everything downstream depends inward on these. The ingestion layer is the *only* code that
  touches YAML.
- **The central architectural bet (write it down in ADR-0002):** the rulebook YAML and a dbt
  manifest both compile to the *same* registry. So the rulebook schema is intentionally
  shaped to mirror dbt/MetricFlow concepts (entities/relationships, measures, filters) — if
  it diverges, Phase 7 gets expensive. This phase proves the bet on the YAML side.
- **`schema.sql` (DuckDB DDL with PK/FK):** explicit constraints so referential integrity is
  enforceable and the grain model is grounded in real keys, not convention.
- **`generate.py` (seeded, deterministic, offline):** stdlib `random.Random(seed)` only — no
  numpy, no pandas (§6), no Faker (a dependency + a nondeterminism risk). Hard row caps in
  *code*. Writes rows into a DuckDB file.
- **CLI `ledgerbench world build [--world all|saas|finance] [--seed N]`:** produces `.duckdb`
  files locally (gitignored, never committed). Thin shell over a builder.
- **Reliability/perf/security:** golden hash tests + integrity tests + a hypothesis seed
  test; `< 30s` build per world; generators offline and writing only inside the workspace;
  the rulebook is *parsed* (pydantic), never `eval`'d.

## 3. Walkthrough — what will be built

New/filled modules (logic lands here for the first time):
- `registry/definitions.py` — `MetricDefinition` + `DefinitionRegistry` (pydantic v2).
- `registry/grain_model.py` — `TableGrain`, `Relationship`, `GrainModel`, with a
  `cardinality(from, to)` lookup.
- `ingestion/rulebook.py` — `load_rulebook(path) -> (DefinitionRegistry, GrainModel)`:
  parse YAML (pyyaml), validate via pydantic, raise typed errors on malformed/invalid input.
- `errors.py` — add `RulebookError` / `RulebookValidationError`.
- `cli.py` — add the `world build` subcommand.
- A thin **world builder** (proposed `src/ledgerbench/worlds.py`): given a world name, run its
  `schema.sql` then call its generator, into a `.duckdb`. (How it invokes the per-world
  generator is **open decision #1**.)
- `benchmark/worlds/saas/{schema.sql, generate.py, rulebook.yaml}` and `finance/{…}` — the
  actual worlds, with planted preconditions documented in rulebook comments.
- Tests: `tests/golden/worlds/` (byte-hash per world per seed), rulebook validation incl.
  malformed YAML, integrity queries (orphan-FK count = 0), the trap-class checklist test, and
  a hypothesis test that a *different* seed changes data but not schema.
- Docs: `docs/architecture.md` worlds section; a rulebook format reference; **ADR-0002**.

**Proposed concrete schemas** (so every trap class has a precondition in *both* worlds):

*SaaS* — `customers, subscriptions, orders, order_items, shipments, users, events`
- definitional: `revenue = sum(orders.amount) where status='completed'`, excluding refunds.
- grain (fan-out): `orders` 1→many `shipments`; the revenue measure is on `orders`.
- ambiguity: both `active_7d` and `active_30d` defined over `events`.
- refusal: no acquisition-channel/marketing-source dimension exists → "revenue by channel"
  is unanswerable and must be refused, naming the missing dimension.
- period/timezone: `events.event_ts` stored UTC with a declared reporting timezone.
- control: clean metrics that should just work (guards against winning by refusing).
- planted, documented: some null `customers.region`; duplicate `events` rows.

*Finance* — `accounts, transactions, ledger_entries, fiscal_periods`
- definitional: `net_revenue` excluding `void`/`pending` transactions.
- grain (fan-out): `transactions` 1→many `ledger_entries`; the amount measure on `transactions`.
- ambiguity: "revenue" defined two ways (gross vs net), both declared.
- refusal: no `cost_center` dimension → "spend by cost center" must be refused.
- period: `fiscal_periods` with a non-January fiscal-year offset; `transactions.txn_ts` UTC
  with a declared local timezone → period/fiscal/timezone traps.
- control: clean fiscal-period totals.
- planted, documented: a small number of nulls + one intentional near-duplicate, all logged.

**Alternatives considered (→ ADR-0002):** stdlib `random` vs numpy/Faker (stdlib: small deps,
explicit determinism); commit `.duckdb` vs regenerate-from-seed (regenerate: small repo,
proves reproducibility); YAML vs Python/JSON rulebook (YAML: human-authored, inline comments
for planted preconditions, pydantic-validated); one world vs two (two: domain breadth + a
natural home for fiscal/timezone preconditions; capped at two per §17).

## 4. Red-team summary (§13)

Key decisions reviewed: seeded stdlib generation; rulebook-YAML-as-canonical; planted
preconditions; hard row caps; two worlds; builder→generator invocation.

- **Software Engineer:** no unseeded randomness (review rule); malformed YAML fails *typed*,
  never crashes. Tested directly.
- **Staff Engineer:** the registry types are the leverage for Phases 3/5/7 — keep the YAML
  shape from leaking downstream; everything consumes `DefinitionRegistry`/`GrainModel` only.
- **Solutions Architect:** shape the rulebook to mirror dbt semantic-model concepts now, or
  Phase 7's compile-to-same-registry bet gets costly. ADR-0002 commits the mapping.
- **Product Engineer:** `world build` must stay `< 30s` so the Phase 6 demo is snappy — row
  caps enforce it.
- **DevOps Engineer:** byte-reproducibility via golden hash tests; generation offline (CI has
  no network); `.duckdb` gitignored so no large artifacts land in git.
- **Security Engineer:** generators are offline and write only inside the workspace; the
  rulebook is parsed, not executed; the builder runs *trusted repo* DDL (a different trust
  domain from the agent SQL that Phase 4 will sandbox).
- **End User:** the world must look credible — hence deliberate, documented nulls/dupes, not
  a suspiciously pristine dataset.
- **Failure modes & the alternative that lost:** hidden nondeterminism (dict/set ordering,
  wall-clock seeds) → byte-diff across runs; mitigated by explicit seeds, sorted iteration,
  no clock, and the golden hash test. The rejected alternative is *committing the `.duckdb`
  files* for speed — it bloats the repo and, worse, lets the data silently drift from the
  generator, destroying the reproducibility claim.
- **Proposed register addition:** **RT-010 — deterministic generation: hidden
  nondeterminism risk → seed everything, no wall-clock, sorted iteration, golden hash tests.**

## 5. Open decisions (your call before coding)

1. **Builder → generator invocation.** `generate.py` lives under `benchmark/` (outside the
   `src/` package). My recommendation: each world dir exposes `def build(con, seed) -> None`
   plus `schema.sql`, and a thin `src/ledgerbench/worlds.py` discovers worlds by directory
   and loads `generate.py` via `importlib.util` to call `build`. Keeps worlds as data-adjacent
   scripts. Alternative: describe worlds entirely inside `src`. **Recommend the former.**
2. **Concrete schemas.** Do you want to review/adjust the proposed `saas`/`finance` table
   lists above before I build them, or trust me to design them to host every precondition
   (and you review in the PR)? **Recommend: proceed with the proposed shapes; you review the PR.**
3. **Rulebook schema scope.** Model exactly the fields the taxonomy preconditions require
   (metrics + filters/exclusions + value_type, table grains, relationships/cardinalities,
   fiscal calendar, timezones, declared irregularities) and no more, deferring richer
   semantic fields until Phase 5/7 needs them. **Recommend: yes, minimal-but-sufficient.**
4. **Determinism mechanism.** stdlib `random.Random(seed)` only, no numpy. **Recommend: yes.**
5. **Built-DB location.** Where `.duckdb` files are written (e.g. `.ledgerbench/worlds/` or
   `build/worlds/`), gitignored either way. **Recommend `.ledgerbench/worlds/`.**

Carry-over from Phase 0 (not blocking Phase 1, your call when convenient): (a) verify
`kartikeya.mandhar@yahoo.in` is a verified email on your GitHub account for profile
attribution, or switch repo-local email to the noreply; (b) delete the merged remote branch
`phase/0-foundation`.
