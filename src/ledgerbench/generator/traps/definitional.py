"""Definitional traps from declared metric filters and exclusions.

A metric that declares filters or exclusions is a definitional hazard: the
naive reading ("just sum the column") silently includes what the business
excludes. Questions are phrased without restating the filters; gold is the
metric itself. Provenance lives in the rubric (the Item contract is frozen).
"""

from __future__ import annotations

from ledgerbench.contracts.item import Item
from ledgerbench.ingestion.dbt_manifest import DbtSemantics

_PHRASINGS = (
    "What was total {name}?",
    "How much {name} do we have overall?",
    "What does {name} come to across the data?",
    "Report total {name}.",
)


def generate(sem: DbtSemantics) -> tuple[list[Item], str | None]:
    """One item per phrasing per metric that declares filters or exclusions."""
    hazardous = [m for m in sem.registry.metrics.values() if m.filters or m.exclusions]
    if not hazardous:
        return [], "no metric declares filters or exclusions"
    items: list[Item] = []
    for metric in sorted(hazardous, key=lambda m: m.id):
        name = metric.id.replace("_", " ")
        for phrasing in _PHRASINGS:
            items.append(
                Item(
                    id=f"byo-def-{len(items) + 1:03d}",
                    world=sem.project_name,
                    question=phrasing.format(name=name),
                    trap_class="definitional",
                    expected_action="answer",
                    gold_recipe={"metric_id": metric.id},
                    rubric=(
                        f"Generated from dbt model {metric.base_table!r} metric "
                        f"{metric.id!r}; gold applies its declared filters "
                        f"{list(metric.filters)} and exclusions {list(metric.exclusions)}."
                    ),
                    version="generated_v1",
                )
            )
    return items, None
