"""Unit tests for the DefinitionRegistry and GrainModel."""

from __future__ import annotations

import pytest

from ledgerbench.errors import LedgerBenchError
from ledgerbench.registry.definitions import DefinitionRegistry, MetricDefinition
from ledgerbench.registry.grain_model import GrainModel, Relationship, TableGrain


def _registry() -> DefinitionRegistry:
    revenue = MetricDefinition(
        id="revenue",
        description="completed revenue",
        base_table="orders",
        measure="sum(amount)",
        value_type="numeric",
        grain=("order_id",),
        exclusions=("refunded = true",),
    )
    count = MetricDefinition(
        id="order_count",
        description="orders",
        base_table="orders",
        measure="count(*)",
        value_type="count",
        grain=("order_id",),
    )
    return DefinitionRegistry(metrics={"revenue": revenue, "order_count": count})


def _grain() -> GrainModel:
    return GrainModel(
        tables={
            "orders": TableGrain(table="orders", grain=("order_id",), primary_key=("order_id",)),
            "shipments": TableGrain(
                table="shipments", grain=("shipment_id",), primary_key=("shipment_id",)
            ),
        },
        relationships=(
            Relationship(
                name="shipments_to_orders",
                from_table="shipments",
                to_table="orders",
                from_columns=("order_id",),
                to_columns=("order_id",),
                cardinality="many_to_one",
            ),
        ),
    )


def test_registry_get_and_ids() -> None:
    registry = _registry()
    assert registry.get("revenue").measure == "sum(amount)"
    assert registry.ids() == ["order_count", "revenue"]
    assert len(registry) == 2


def test_registry_get_unknown_raises() -> None:
    with pytest.raises(LedgerBenchError):
        _registry().get("nope")


def test_metric_definition_is_frozen() -> None:
    metric = _registry().get("revenue")
    with pytest.raises(Exception, match=r"frozen|immutable"):
        metric.measure = "sum(x)"  # type: ignore[misc]


def test_cardinality_both_directions_and_missing() -> None:
    grain = _grain()
    assert grain.cardinality("shipments", "orders") == "many_to_one"
    # Reverse direction is inferred as the inverse.
    assert grain.cardinality("orders", "shipments") == "one_to_many"
    assert grain.cardinality("orders", "customers") is None


def test_fans_out_only_on_one_to_many() -> None:
    grain = _grain()
    assert grain.fans_out("orders", "shipments") is True
    assert grain.fans_out("shipments", "orders") is False
    assert grain.fans_out("orders", "customers") is False
