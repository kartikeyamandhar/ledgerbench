"""Compile a rulebook YAML file into a validated :class:`Rulebook`.

The rulebook is the law: it declares a world's tables, relationships, metrics, and
the documented irregularities that make the data realistic without making gold
uncomputable. This module is the *only* place that touches YAML; everything
downstream consumes the projected :class:`DefinitionRegistry` and
:class:`GrainModel`. A dbt manifest will compile into the same structures in
Phase 7 (see ADR-0002).
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ledgerbench.errors import RulebookError, RulebookValidationError
from ledgerbench.registry.definitions import DefinitionRegistry, MetricDefinition, ValueType
from ledgerbench.registry.grain_model import Cardinality, GrainModel, Relationship, TableGrain


class TableSpec(BaseModel):
    """A table declaration in the rulebook."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    grain: tuple[str, ...]
    primary_key: tuple[str, ...]
    description: str = ""


class RelationshipSpec(BaseModel):
    """A relationship declaration in the rulebook."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    from_table: str
    to_table: str
    from_columns: tuple[str, ...]
    to_columns: tuple[str, ...]
    cardinality: Cardinality


class MetricSpec(BaseModel):
    """A metric declaration in the rulebook."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    description: str
    base_table: str = Field(min_length=1)
    measure: str = Field(min_length=1)
    value_type: ValueType
    grain: tuple[str, ...]
    filters: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()


class AmbiguitySpec(BaseModel):
    """A documented ambiguous term with two or more defensible readings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    term: str
    readings: tuple[str, ...] = Field(min_length=2)
    note: str = ""


class AbsentDimensionSpec(BaseModel):
    """A plausible-but-absent dimension; the target for a refusal item."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    note: str = ""


class IrregularitySpec(BaseModel):
    """A deliberately planted, documented data irregularity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    table: str
    kind: Literal["nulls", "duplicates"]
    column: str | None = None
    note: str = ""


class Rulebook(BaseModel):
    """A validated rulebook for one world.

    Beyond the registry and grain model, it carries the metadata that the trap
    taxonomy needs preconditions for: ambiguities (ambiguity items), absent
    dimensions (refusal items), and the reporting timezone / fiscal offset
    (period items). The acceptance checklist test reads these directly.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    world: str = Field(min_length=1)
    description: str = ""
    timezone: str = "UTC"
    reporting_timezone: str | None = None
    fiscal_year_start_month: int = Field(default=1, ge=1, le=12)
    reference_date: datetime.date
    tables: tuple[TableSpec, ...] = Field(min_length=1)
    relationships: tuple[RelationshipSpec, ...] = ()
    metrics: tuple[MetricSpec, ...] = Field(min_length=1)
    ambiguities: tuple[AmbiguitySpec, ...] = ()
    absent_dimensions: tuple[AbsentDimensionSpec, ...] = ()
    irregularities: tuple[IrregularitySpec, ...] = ()

    @model_validator(mode="after")
    def _check_internal_references(self) -> Rulebook:
        """Reject rulebooks whose parts reference things they do not declare."""
        table_names = {t.name for t in self.tables}

        metric_ids = [m.id for m in self.metrics]
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("duplicate metric ids in rulebook")

        for rel in self.relationships:
            for tbl in (rel.from_table, rel.to_table):
                if tbl not in table_names:
                    raise ValueError(f"relationship {rel.name!r} references unknown table {tbl!r}")

        for metric in self.metrics:
            if metric.base_table not in table_names:
                raise ValueError(
                    f"metric {metric.id!r} references unknown base_table {metric.base_table!r}"
                )

        metric_id_set = set(metric_ids)
        for amb in self.ambiguities:
            for reading in amb.readings:
                if reading not in metric_id_set:
                    raise ValueError(
                        f"ambiguity {amb.term!r} references unknown metric {reading!r}"
                    )

        irregular_tables = {irr.table for irr in self.irregularities}
        if not irregular_tables <= table_names:
            unknown = ", ".join(sorted(irregular_tables - table_names))
            raise ValueError(f"irregularity references unknown table(s): {unknown}")

        return self

    def to_registry(self) -> DefinitionRegistry:
        """Project the declared metrics into a :class:`DefinitionRegistry`."""
        return DefinitionRegistry(
            metrics={m.id: MetricDefinition(**m.model_dump()) for m in self.metrics}
        )

    def to_grain_model(self) -> GrainModel:
        """Project the declared tables and relationships into a :class:`GrainModel`."""
        return GrainModel(
            tables={
                t.name: TableGrain(table=t.name, grain=t.grain, primary_key=t.primary_key)
                for t in self.tables
            },
            relationships=tuple(Relationship(**r.model_dump()) for r in self.relationships),
        )


def load_rulebook(path: str | Path) -> Rulebook:
    """Read, parse, and validate a rulebook YAML file.

    Args:
        path: Path to the rulebook YAML file.

    Returns:
        The validated :class:`Rulebook`.

    Raises:
        RulebookError: the file cannot be read or is not valid YAML.
        RulebookValidationError: the YAML is well-formed but fails schema or
            semantic validation (e.g. an unknown table reference).
    """
    rulebook_path = Path(path)
    try:
        text = rulebook_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RulebookError(f"cannot read rulebook {rulebook_path}: {exc}") from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RulebookError(f"rulebook {rulebook_path} is not valid YAML: {exc}") from exc

    if not isinstance(data, dict):
        kind = type(data).__name__
        raise RulebookValidationError(
            f"rulebook {rulebook_path} must be a YAML mapping, got {kind}"
        )

    try:
        return Rulebook.model_validate(data)
    except ValidationError as exc:
        raise RulebookValidationError(
            f"rulebook {rulebook_path} failed validation:\n{exc}"
        ) from exc
