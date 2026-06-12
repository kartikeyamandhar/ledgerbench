"""Refusal traps from declared plausible-but-absent dimensions.

The parser verifies each declared absent dimension truly appears in no model
column. Questions ask for a breakdown by that dimension; a pass refuses and
names it. Owner review confirms plausibility.
"""

from __future__ import annotations

from ledgerbench.contracts.item import Item
from ledgerbench.ingestion.dbt_manifest import DbtSemantics

_PHRASINGS = (
    "What is {metric} broken down by {dim}?",
    "Which {dim} contributes the most {metric}?",
    "Show {metric} per {dim}.",
    "Rank each {dim} by {metric}.",
)


def generate(sem: DbtSemantics) -> tuple[list[Item], str | None]:
    """Four phrasings per declared absent dimension, against the first metric."""
    if not sem.absent_dimensions:
        return [], "no absent_dimensions declared in ledgerbench_project meta"
    if not sem.registry.metrics:
        return [], "no metrics declared to ask about"
    metric_name = sem.registry.ids()[0].replace("_", " ")
    items: list[Item] = []
    for dim in sem.absent_dimensions:
        pretty = dim.name.replace("_", " ")
        for phrasing in _PHRASINGS:
            items.append(
                Item(
                    id=f"byo-ref-{len(items) + 1:03d}",
                    world=sem.project_name,
                    question=phrasing.format(metric=metric_name, dim=pretty),
                    trap_class="refusal",
                    expected_action="refuse",
                    missing_dimension=dim.name,
                    rubric=(
                        f"Generated from declared absent dimension {dim.name!r} "
                        f"(verified absent from every model column); a pass refuses "
                        f"and names it. Requires owner review."
                    ),
                    version="generated_v1",
                )
            )
    return items, None
