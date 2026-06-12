"""Fan-out traps from one-to-many relationships carrying measures.

Where a relationship's parent table carries a metric, asking about the metric
"for parents having children" tempts a join that multiplies the measure. Gold
restricts by existence (an IN-subquery), which cannot fan out by construction.
"""

from __future__ import annotations

from ledgerbench.contracts.item import Item
from ledgerbench.ingestion.dbt_manifest import DbtSemantics

_PHRASINGS = (
    "What is {name} for {parent} records that have at least one {child} record?",
    "Considering {child}, what is {name} from {parent} rows with {child} entries?",
)


def generate(sem: DbtSemantics) -> tuple[list[Item], str | None]:
    """Per (1:N relationship, parent metric): existence-restricted questions."""
    items: list[Item] = []
    for rel in sem.relationships:
        parent, child = rel.to_table, rel.from_table
        metrics = [m for m in sem.registry.metrics.values() if m.base_table == parent]
        for metric in sorted(metrics, key=lambda m: m.id):
            predicate = f"{rel.to_columns[0]} IN (SELECT {rel.from_columns[0]} FROM {child})"
            name = metric.id.replace("_", " ")
            for phrasing in _PHRASINGS:
                items.append(
                    Item(
                        id=f"byo-grain-{len(items) + 1:03d}",
                        world=sem.project_name,
                        question=phrasing.format(name=name, parent=parent, child=child),
                        trap_class="grain",
                        expected_action="answer",
                        gold_recipe={
                            "metric_id": metric.id,
                            "params": {"extra_where": [predicate]},
                        },
                        declared_grain=list(rel.to_columns),
                        rubric=(
                            f"Generated from dbt relationship test {rel.name!r} "
                            f"({child} -> {parent}, many_to_one): joining {child} "
                            f"multiplies {metric.measure}; gold restricts by existence."
                        ),
                        version="generated_v1",
                    )
                )
    if not items:
        return [], "no one-to-many relationship has a metric on its one side"
    return items, None
