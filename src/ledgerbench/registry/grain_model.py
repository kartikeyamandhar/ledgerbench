"""Table grains and relationship cardinalities.

This is the structural half of a world's semantics (the metric half lives in
:mod:`ledgerbench.registry.definitions`). Phase 3's static grain checker reads
this model to decide whether an agent's SQL inflates a measure through a
one-to-many join (a fan trap).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Cardinality = Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]

_INVERSE: dict[Cardinality, Cardinality] = {
    "one_to_one": "one_to_one",
    "one_to_many": "many_to_one",
    "many_to_one": "one_to_many",
    "many_to_many": "many_to_many",
}


class TableGrain(BaseModel):
    """What one row of a table represents.

    Attributes:
        table: Table name.
        grain: Columns that uniquely identify one row's meaning.
        primary_key: The declared primary key (often equal to ``grain``).
    """

    model_config = ConfigDict(frozen=True)

    table: str = Field(min_length=1)
    grain: tuple[str, ...]
    primary_key: tuple[str, ...]


class Relationship(BaseModel):
    """A foreign-key relationship between two tables, with its cardinality.

    Cardinality is read ``from_table -> to_table``. For example, shipments to
    orders is ``many_to_one`` (many shipments per order), which means orders to
    shipments is ``one_to_many`` -- the direction that inflates a measure on
    orders.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    from_table: str
    to_table: str
    from_columns: tuple[str, ...]
    to_columns: tuple[str, ...]
    cardinality: Cardinality


class GrainModel(BaseModel):
    """The grains and relationships of every table in one world."""

    model_config = ConfigDict(frozen=True)

    tables: dict[str, TableGrain]
    relationships: tuple[Relationship, ...] = ()

    def cardinality(self, from_table: str, to_table: str) -> Cardinality | None:
        """Return the cardinality from ``from_table`` to ``to_table``.

        Checks declared relationships in both directions: a ``many_to_one``
        edge declared one way answers the ``one_to_many`` query the other way.
        Returns ``None`` if the two tables have no declared relationship.
        """
        for rel in self.relationships:
            if rel.from_table == from_table and rel.to_table == to_table:
                return rel.cardinality
            if rel.from_table == to_table and rel.to_table == from_table:
                return _INVERSE[rel.cardinality]
        return None

    def fans_out(self, from_table: str, to_table: str) -> bool:
        """Whether joining ``from_table`` to ``to_table`` multiplies rows.

        True when the relationship is ``one_to_many`` or ``many_to_many`` -- the
        shapes that can double-count a measure anchored on ``from_table``.
        """
        return self.cardinality(from_table, to_table) in ("one_to_many", "many_to_many")
