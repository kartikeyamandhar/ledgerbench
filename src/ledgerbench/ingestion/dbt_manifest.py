"""Compile a dbt ``manifest.json`` into the same registry the rulebooks use.

The central architectural bet, cashed: downstream code consumes only
:class:`~ledgerbench.registry.definitions.DefinitionRegistry` and
:class:`~ledgerbench.registry.grain_model.GrainModel`, so pointing LedgerBench
at a real dbt project is "swap the loader" -- this module is that loader.

What it reads (declared semantics only -- nothing is inferred from model SQL,
and no LLM is anywhere near this path):

- models -> tables and columns;
- ``unique`` tests -> primary keys / grains (models without one get a sentinel
  key that can never match a join column -- fail-closed for the grain checker);
- ``relationships`` tests -> ``many_to_one`` edges (foreign-key semantics);
- ``meta.ledgerbench.metrics`` blocks on models -> metric definitions
  (the version-stable, explicit channel; MetricFlow ingestion is post-launch);
- ``meta.ledgerbench_project`` blocks -> project declarations (reporting
  timezone, fiscal calendar, ambiguous terms, absent dimensions).

Supported manifest schema versions: v11-v12 (dbt-core ~1.7-1.9). Anything else
fails fast with the found version, the supported range, and the fix.
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ledgerbench.errors import LedgerBenchError
from ledgerbench.registry.definitions import DefinitionRegistry, MetricDefinition
from ledgerbench.registry.grain_model import GrainModel, Relationship, TableGrain

SUPPORTED_SCHEMA_VERSIONS = (11, 12)

UNDECLARED_KEY = "__undeclared_primary_key__"
"""Sentinel grain for models without a unique test; never matches a join column."""

_SCHEMA_VERSION = re.compile(r"/v(\d+)\.json$")
_REF = re.compile(r"ref\(\s*['\"]([^'\"]+)['\"]\s*\)")


class AmbiguousTerm(BaseModel):
    """A declared term with two or more defensible metric readings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    term: str = Field(min_length=1)
    readings: tuple[str, ...] = Field(min_length=2)


class ProjectDeclarations(BaseModel):
    """Project-level declarations from ``meta.ledgerbench_project`` blocks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reporting_timezone: str | None = None
    fiscal_year_start_month: int = Field(default=1, ge=1, le=12)
    absent_dimensions: tuple[str, ...] = ()
    ambiguous_terms: tuple[AmbiguousTerm, ...] = ()


class AbsentDimension(BaseModel):
    """A declared plausible-but-absent dimension (refusal precondition)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)


class DbtSemantics(BaseModel):
    """Everything LedgerBench extracted from one dbt project.

    Exposes the same duck-typed surface as a world Rulebook (``ambiguities``,
    ``absent_dimensions``, ``relationships``, ``reporting_timezone``,
    ``reference_date``, ``to_registry``), so ``validate_items`` and the rest of
    the engine treat a dbt project exactly like a bundled world.
    """

    model_config = ConfigDict(frozen=True)

    project_name: str
    registry: DefinitionRegistry
    grain_model: GrainModel
    declarations: ProjectDeclarations
    columns_by_table: dict[str, tuple[str, ...]]
    time_columns: dict[str, str]  # metric id -> declared time column
    reference_date: datetime.date = datetime.date(2026, 1, 1)

    @property
    def ambiguities(self) -> tuple[AmbiguousTerm, ...]:
        """Declared ambiguous terms (rulebook-compatible surface)."""
        return self.declarations.ambiguous_terms

    @property
    def absent_dimensions(self) -> tuple[AbsentDimension, ...]:
        """Declared absent dimensions (rulebook-compatible surface)."""
        return tuple(AbsentDimension(name=d) for d in self.declarations.absent_dimensions)

    @property
    def relationships(self) -> tuple[Relationship, ...]:
        """Declared relationships (rulebook-compatible surface)."""
        return self.grain_model.relationships

    @property
    def reporting_timezone(self) -> str | None:
        """Declared reporting timezone (rulebook-compatible surface)."""
        return self.declarations.reporting_timezone

    def to_registry(self) -> DefinitionRegistry:
        """Return the metric registry (rulebook-compatible surface)."""
        return self.registry


def _check_schema_version(metadata: dict[str, Any], path: Path) -> None:
    url = str(metadata.get("dbt_schema_version", ""))
    match = _SCHEMA_VERSION.search(url)
    found = int(match.group(1)) if match else None
    if found not in SUPPORTED_SCHEMA_VERSIONS:
        supported = ", ".join(f"v{v}" for v in SUPPORTED_SCHEMA_VERSIONS)
        raise LedgerBenchError(
            f"{path}: unsupported dbt manifest schema "
            f"{'v' + str(found) if found else url!r}; supported: {supported} "
            f"(dbt-core ~1.7-1.9). Re-generate the manifest with a supported dbt "
            f"version, or open an issue with your manifest's metadata block."
        )


def _ref_target(kwargs: dict[str, Any]) -> str | None:
    match = _REF.search(str(kwargs.get("to", "")))
    return match.group(1) if match else None


def load_dbt_manifest(path: str | Path) -> DbtSemantics:
    """Parse a dbt manifest into registry + grain model + declarations.

    Raises:
        LedgerBenchError: unreadable/invalid JSON, unsupported schema version,
            or declared semantics that fail validation (bad metric block,
            relationship to an unknown model, absent dimension that exists).
    """
    manifest_path = Path(path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LedgerBenchError(f"cannot read manifest {manifest_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LedgerBenchError(f"{manifest_path} is not valid JSON: {exc}") from exc

    metadata = manifest.get("metadata", {})
    _check_schema_version(metadata, manifest_path)
    nodes: dict[str, dict[str, Any]] = manifest.get("nodes", {})

    models = {node["name"]: node for node in nodes.values() if node.get("resource_type") == "model"}
    tests = [node for node in nodes.values() if node.get("resource_type") == "test"]

    columns_by_table = {name: tuple(node.get("columns", {})) for name, node in models.items()}

    # Primary keys from unique tests; sentinel where undeclared (fail closed).
    primary_keys: dict[str, list[str]] = {name: [] for name in models}
    relationships: list[Relationship] = []
    for test in tests:
        test_meta = test.get("test_metadata") or {}
        kwargs = test_meta.get("kwargs") or {}
        column = kwargs.get("column_name")
        attached = str(test.get("attached_node", ""))
        owner = attached.rsplit(".", 1)[-1] if attached else None
        if owner is None or owner not in models or not column:
            continue
        if test_meta.get("name") == "unique":
            primary_keys[owner].append(str(column))
        elif test_meta.get("name") == "relationships":
            parent = _ref_target(kwargs)
            if parent is None or parent not in models:
                raise LedgerBenchError(
                    f"relationships test {test.get('name')!r} points at unknown model "
                    f"{kwargs.get('to')!r}"
                )
            relationships.append(
                Relationship(
                    name=str(test.get("name", f"{owner}_to_{parent}")),
                    from_table=owner,
                    to_table=parent,
                    from_columns=(str(column),),
                    to_columns=(str(kwargs.get("field", column)),),
                    cardinality="many_to_one",
                )
            )

    tables = {
        name: TableGrain(
            table=name,
            grain=tuple(primary_keys[name]) or (UNDECLARED_KEY,),
            primary_key=tuple(primary_keys[name]) or (UNDECLARED_KEY,),
        )
        for name in models
    }

    # Metrics and project declarations from meta blocks.
    metrics: dict[str, MetricDefinition] = {}
    time_columns: dict[str, str] = {}
    project_blocks: list[dict[str, Any]] = []
    for name, node in models.items():
        meta = {**(node.get("config", {}).get("meta") or {}), **(node.get("meta") or {})}
        if "ledgerbench_project" in meta:
            project_blocks.append(meta["ledgerbench_project"])
        for raw in (meta.get("ledgerbench") or {}).get("metrics", []):
            block = dict(raw)
            time_column = block.pop("time_column", None)
            try:
                definition = MetricDefinition(
                    base_table=name,
                    grain=tables[name].grain,
                    description=block.pop("description", ""),
                    **block,
                )
            except (ValidationError, TypeError) as exc:
                raise LedgerBenchError(
                    f"model {name!r}: invalid meta.ledgerbench metric block: {exc}"
                ) from exc
            if definition.id in metrics:
                raise LedgerBenchError(f"duplicate metric id {definition.id!r} across models")
            metrics[definition.id] = definition
            if time_column is not None:
                if time_column not in columns_by_table[name]:
                    raise LedgerBenchError(
                        f"metric {definition.id!r}: time_column {time_column!r} is not a "
                        f"column of {name!r}"
                    )
                time_columns[definition.id] = str(time_column)

    merged: dict[str, Any] = {}
    for block in project_blocks:
        merged.update(block)
    try:
        declarations = ProjectDeclarations.model_validate(merged)
    except ValidationError as exc:
        raise LedgerBenchError(f"invalid ledgerbench_project declarations: {exc}") from exc

    for term in declarations.ambiguous_terms:
        unknown = [r for r in term.readings if r not in metrics]
        if unknown:
            raise LedgerBenchError(
                f"ambiguous term {term.term!r} references undeclared metrics: {unknown}"
            )
    all_columns = {c for cols in columns_by_table.values() for c in cols}
    present = [d for d in declarations.absent_dimensions if d in all_columns]
    if present:
        raise LedgerBenchError(f"declared absent_dimensions actually exist as columns: {present}")

    return DbtSemantics(
        project_name=str(metadata.get("project_name", "dbt_project")),
        registry=DefinitionRegistry(metrics=metrics),
        grain_model=GrainModel(tables=tables, relationships=tuple(relationships)),
        declarations=declarations,
        columns_by_table=columns_by_table,
        time_columns=time_columns,
    )
