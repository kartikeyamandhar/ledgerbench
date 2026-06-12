"""Ambiguity traps from declared multiply-defined terms.

Only terms the project itself declares ambiguous (two or more metric readings)
become items -- the generator never invents ambiguity, and the review step
exists because only the owner can confirm the term is genuinely two-readinged
for their business.
"""

from __future__ import annotations

from ledgerbench.contracts.item import Item
from ledgerbench.ingestion.dbt_manifest import DbtSemantics

_PHRASINGS = (
    "What was {term}?",
    "How much {term} did we have?",
    "Report total {term}.",
    "What is our {term} number?",
)


def generate(sem: DbtSemantics) -> tuple[list[Item], str | None]:
    """Four phrasings per declared ambiguous term."""
    if not sem.ambiguities:
        return [], "no ambiguous_terms declared in ledgerbench_project meta"
    items: list[Item] = []
    for amb in sem.ambiguities:
        for phrasing in _PHRASINGS:
            items.append(
                Item(
                    id=f"byo-amb-{len(items) + 1:03d}",
                    world=sem.project_name,
                    question=phrasing.format(term=amb.term),
                    trap_class="ambiguity",
                    expected_action="clarify",
                    ambiguous_term=amb.term,
                    rubric=(
                        f"Generated from declared ambiguous term {amb.term!r} with "
                        f"readings {list(amb.readings)}; a pass clarifies and names "
                        f"the term. Requires owner review."
                    ),
                    version="generated_v1",
                )
            )
    return items, None
