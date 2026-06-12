# The public item bank (`public_v1.jsonl`)

150 exam questions across the two bundled worlds, engineered so that each item
triggers exactly one failure class. Versioned and **append-only**: corrections
ship as `public_v1.1` with a changelog entry, never as silent edits.

## Taxonomy

| Class | Count | Expected behavior | The trap |
|---|---|---|---|
| definitional | 40 | answer | naive readings miss the declared filters/exclusions (refunds, void/pending) |
| grain | 30 | answer | the question invites a 1:N join that multiplies the measure; the correct reading restricts by existence |
| ambiguity | 25 | clarify (naming the term) | the rulebook declares two defensible readings ("active users" 7d/30d; "revenue" gross/net) |
| refusal | 20 | refuse (naming the dimension) | the dimension is plausible but absent from the schema (acquisition channel, cost center) |
| period | 15 | answer | UTC storage vs New York reporting time; February-start fiscal calendar |
| control | 20 | answer | none — fully specified questions; refusing one is the over-refusal penalty |

## Why this is not author opinion (the anti-subjectivity argument)

No item carries a baked answer. Every `answer` item carries a **gold recipe** — a
rulebook metric id plus an optional `extra_where` window — and gold is *derived* by
compiling that recipe against the world (`gold/compiler.py`) at validation and run
time. Disagree with a gold value? The disagreement is with the world's declared
rulebook, which is public, versioned, and mechanical — not with the author's reading
of the question. Ambiguity items use only terms the rulebook *declares* ambiguous
(both readings exist as metrics); refusal items use only dimensions the rulebook
*declares* absent. The linter enforces all of this in CI.

## Item shape

See `docs/contracts.md` and `docs/contracts/Item.json`. Every item has a `rubric` a
stranger could grade with by hand.

## Authoring guide (for `public_v1.1`+ and community items)

1. Pick the trap class first; one item = one failure class.
2. Answer items: express gold as `{"metric_id": ..., "params": {"extra_where": [...]}}`.
   If the gold needs anything richer, the rulebook (not the item) is missing a
   declaration — fix it there.
3. Ambiguity items must use a declared ambiguous term and set `ambiguous_term`;
   refusal items must use a declared absent dimension and set `missing_dimension`.
4. Grain items must set `declared_grain` and stay inside the grain checker's
   supported-constructs fence (see ADR-0004) so axis 2 can adjudicate them.
5. Run `ledgerbench validate <file>` — it must pass, including gold recomputation.
6. Append, never edit. Bump the suite version for any correction.

## The private split

A 30-item split lives in a separate private repository and is never committed,
referenced, or quoted here in any form. Protocol: `docs/private-split.md`.
