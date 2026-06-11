"""Metric definitions: the semantic layer the scorer and gold compiler consume.

A :class:`DefinitionRegistry` is the canonical, source-agnostic form of "what a
metric means". Rulebook YAML compiles into it today; a dbt manifest compiles into
the same structure in Phase 7. Nothing downstream looks at raw YAML, which is what
lets BYO mode swap the loader and change nothing else.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ledgerbench.errors import LedgerBenchError

ValueType = Literal["numeric", "count"]
"""How a metric's value is compared to gold.

``numeric`` values reconcile within a relative tolerance; ``count`` values are
integer cardinalities and must match exactly (the rule is enforced in Phase 2).
"""


class MetricDefinition(BaseModel):
    """A single business metric, declared independently of any agent or query.

    Attributes:
        id: Stable identifier, unique within a world (e.g. ``"revenue"``).
        description: Human-readable definition; the rulebook is the source of truth.
        base_table: The table the measure is computed over; also the grain anchor
            for fan-out detection (a measure on the "one" side of a one-to-many).
        measure: The aggregate expression, e.g. ``"sum(amount)"``.
        value_type: ``numeric`` or ``count`` (drives the reconciliation rule).
        grain: Columns identifying one row of ``base_table``.
        filters: Inclusion predicates, e.g. ``"status = 'completed'"``.
        exclusions: Exclusion predicates, e.g. ``"refunded = true"``; kept separate
            from filters so the report can explain *what was left out* and why.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    description: str
    base_table: str = Field(min_length=1)
    measure: str = Field(min_length=1)
    value_type: ValueType
    grain: tuple[str, ...]
    filters: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()


class DefinitionRegistry(BaseModel):
    """An immutable lookup of metrics by id for one world."""

    model_config = ConfigDict(frozen=True)

    metrics: dict[str, MetricDefinition]

    def get(self, metric_id: str) -> MetricDefinition:
        """Return the metric with ``metric_id``.

        Raises:
            LedgerBenchError: if no metric with that id is registered.
        """
        try:
            return self.metrics[metric_id]
        except KeyError as exc:
            known = ", ".join(self.ids()) or "(none)"
            msg = f"unknown metric {metric_id!r}; known metrics: {known}"
            raise LedgerBenchError(msg) from exc

    def ids(self) -> list[str]:
        """Return all metric ids, sorted for deterministic output."""
        return sorted(self.metrics)

    def __len__(self) -> int:
        """Return the number of registered metrics."""
        return len(self.metrics)
