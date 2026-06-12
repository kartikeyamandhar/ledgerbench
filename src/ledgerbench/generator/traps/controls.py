"""Clean controls from metrics with no filters or exclusions.

Fully specified, no trap: answering is the only correct behavior, so an agent
cannot win the suite by refusing everything (the over-refusal penalty needs
these to bite).
"""

from __future__ import annotations

from ledgerbench.contracts.item import Item
from ledgerbench.ingestion.dbt_manifest import DbtSemantics

_NUMERIC = (
    "What is total {name}?",
    "Sum up {name} across all rows.",
    "What does {name} total?",
)
_COUNT = (
    "How many rows does {name} count in total?",
    "What is the total {name}?",
    "Report the {name} figure.",
)


def generate(sem: DbtSemantics) -> tuple[list[Item], str | None]:
    """Three phrasings per plain (unfiltered) metric."""
    plain = [m for m in sem.registry.metrics.values() if not m.filters and not m.exclusions]
    if not plain:
        return [], "every declared metric carries filters or exclusions"
    items: list[Item] = []
    for metric in sorted(plain, key=lambda m: m.id):
        name = metric.id.replace("_", " ")
        for phrasing in _COUNT if metric.value_type == "count" else _NUMERIC:
            items.append(
                Item(
                    id=f"byo-ctl-{len(items) + 1:03d}",
                    world=sem.project_name,
                    question=phrasing.format(name=name),
                    trap_class="control",
                    expected_action="answer",
                    gold_recipe={"metric_id": metric.id},
                    rubric=(
                        f"Control generated from dbt model {metric.base_table!r} metric "
                        f"{metric.id!r}; fully specified, refusing is over-refusal."
                    ),
                    version="generated_v1",
                )
            )
    return items, None
