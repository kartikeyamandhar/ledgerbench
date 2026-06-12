"""Item suites: loading, hashing, and the linter that keeps the bank honest.

``validate_items`` is the gate everything item-shaped must pass -- the public
bank in CI, community submissions later, and Phase 7's generated suites. It
checks structure (unique ids, schema validity, taxonomy counts), preconditions
(every trap class's trigger actually exists in its world's rulebook), world
isolation, and -- the expensive, decisive check -- that every answer item's
gold recomputes mechanically from the rulebook against a freshly built world.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ledgerbench.contracts.item import Item
from ledgerbench.errors import LedgerBenchError
from ledgerbench.gold.compiler import compute_gold
from ledgerbench.ingestion.rulebook import Rulebook

if TYPE_CHECKING:
    import duckdb

PUBLIC_TAXONOMY: dict[str, int] = {
    "definitional": 40,
    "grain": 30,
    "ambiguity": 25,
    "refusal": 20,
    "period": 15,
    "control": 20,
}
"""The published taxonomy counts for the 150-item public bank."""


def load_bank(path: str | Path) -> list[Item]:
    """Load and contract-validate a suite JSONL; raises on any invalid line."""
    items = []
    for lineno, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            items.append(Item.model_validate_json(line))
        except ValidationError as exc:
            raise ValueError(f"{path}:{lineno}: invalid item: {exc}") from exc
    return items


def suite_hash(path: str | Path) -> str:
    """Content digest of a suite file, recorded in every RunManifest."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


@dataclass
class LintReport:
    """The linter's findings; empty ``errors`` means the suite is valid."""

    errors: list[str] = field(default_factory=list)
    checked_items: int = 0
    recomputed_gold: int = 0

    @property
    def ok(self) -> bool:
        """Whether the suite passed every check."""
        return not self.errors


def validate_items(
    items: Sequence[Item],
    rulebooks: Mapping[str, Rulebook],
    *,
    connections: Mapping[str, duckdb.DuckDBPyConnection] | None = None,
    expected_taxonomy: Mapping[str, int] | None = None,
) -> LintReport:
    """Lint a suite. Pass ``connections`` to also recompute gold (the CI mode).

    Args:
        items: The suite to validate (already contract-valid).
        rulebooks: World name -> validated rulebook, for precondition checks.
        connections: World name -> open DuckDB connection on a built world;
            when provided, every answer item's gold is recomputed mechanically.
        expected_taxonomy: Exact per-class counts to enforce (the public bank
            uses :data:`PUBLIC_TAXONOMY`); None skips the count check.

    Returns:
        A :class:`LintReport`; ``report.ok`` is the gate.
    """
    report = LintReport(checked_items=len(items))

    ids = [item.id for item in items]
    for item_id, count in sorted(Counter(ids).items()):
        if count > 1:
            report.errors.append(f"duplicate item id {item_id!r} ({count} occurrences)")

    if expected_taxonomy is not None:
        actual = Counter(str(item.trap_class) for item in items)
        for klass, expected in expected_taxonomy.items():
            if actual.get(klass, 0) != expected:
                report.errors.append(
                    f"taxonomy count for {klass!r}: expected {expected}, got {actual.get(klass, 0)}"
                )

    for item in items:
        rulebook = rulebooks.get(item.world)
        if rulebook is None:
            report.errors.append(f"{item.id}: unknown world {item.world!r}")
            continue

        if item.trap_class == "ambiguity":
            declared = {a.term for a in rulebook.ambiguities}
            if item.ambiguous_term not in declared:
                report.errors.append(
                    f"{item.id}: ambiguous_term {item.ambiguous_term!r} is not a "
                    f"declared ambiguity in world {item.world!r} (precondition missing)"
                )
        if item.trap_class == "refusal":
            declared = {d.name for d in rulebook.absent_dimensions}
            if item.missing_dimension not in declared:
                report.errors.append(
                    f"{item.id}: missing_dimension {item.missing_dimension!r} is not a "
                    f"declared absent dimension in world {item.world!r}"
                )
        if item.trap_class == "grain":
            if not item.declared_grain:
                report.errors.append(f"{item.id}: grain items must declare their grain")
            if not any(
                rel.cardinality in ("many_to_one", "one_to_many") for rel in rulebook.relationships
            ):
                report.errors.append(
                    f"{item.id}: world {item.world!r} declares no 1:N relationship"
                )
        if item.trap_class == "period" and rulebook.reporting_timezone is None:
            report.errors.append(f"{item.id}: world {item.world!r} declares no reporting timezone")

        if item.gold_recipe is not None:
            registry = rulebook.to_registry()
            if item.gold_recipe.metric_id not in registry.metrics:
                report.errors.append(
                    f"{item.id}: recipe metric {item.gold_recipe.metric_id!r} is not "
                    f"declared in world {item.world!r} (world isolation)"
                )
            elif connections is not None:
                con = connections.get(item.world)
                if con is None:
                    report.errors.append(f"{item.id}: no connection for {item.world!r}")
                    continue
                definition = registry.get(item.gold_recipe.metric_id)
                try:
                    compute_gold(
                        con,
                        definition,
                        item.gold_recipe,
                        reference_date=rulebook.reference_date,
                    )
                    report.recomputed_gold += 1
                except Exception as exc:
                    report.errors.append(f"{item.id}: gold recomputation failed: {exc}")

    return report


# --- Phase 7: suite generation from a dbt project ---------------------------------


@dataclass(frozen=True)
class CoverageReport:
    """Which trap classes could be generated for this project, and why not.

    The honesty artifact of BYO mode: where a project declares too little for a
    class, the report says so instead of fabricating semantics (RT-016).
    """

    generated: dict[str, int]
    skipped: dict[str, str]

    def render(self) -> str:
        """Human-readable coverage summary for the CLI."""
        lines = ["trap-class coverage:"]
        for klass, count in sorted(self.generated.items()):
            lines.append(f"  {klass:13s} {count} item(s)")
        for klass, reason in sorted(self.skipped.items()):
            lines.append(f"  {klass:13s} SKIPPED -- {reason}")
        return "\n".join(lines)


def generate_suite(
    semantics: object,
    con: duckdb.DuckDBPyConnection,
) -> tuple[list[Item], CoverageReport]:
    """Generate a trap suite from parsed dbt semantics; lint before returning.

    Args:
        semantics: A :class:`~ledgerbench.ingestion.dbt_manifest.DbtSemantics`
            (typed loosely to avoid an import cycle; the generators check).
        con: Read-only warehouse connection (used only for the period
            generator's min/max probes).

    Returns:
        The generated items plus the per-class coverage report. The generated
        suite is validated with :func:`validate_items` before being returned;
        a generator emitting an invalid item is a bug, not a user error.
    """
    from ledgerbench.generator.traps import (
        ambiguity,
        controls,
        definitional,
        grain,
        period,
        refusal,
    )
    from ledgerbench.ingestion.dbt_manifest import DbtSemantics

    assert isinstance(semantics, DbtSemantics)
    generated: dict[str, int] = {}
    skipped: dict[str, str] = {}
    items: list[Item] = []

    classwise: list[tuple[str, tuple[list[Item], str | None]]] = [
        ("definitional", definitional.generate(semantics)),
        ("grain", grain.generate(semantics)),
        ("ambiguity", ambiguity.generate(semantics)),
        ("refusal", refusal.generate(semantics)),
        ("period", period.generate(semantics, con)),
        ("control", controls.generate(semantics)),
    ]
    for klass, (class_items, reason) in classwise:
        if reason is not None:
            skipped[klass] = reason
        else:
            generated[klass] = len(class_items)
            items.extend(class_items)

    report = validate_items(
        items,
        {semantics.project_name: semantics},  # type: ignore[dict-item]
        connections={semantics.project_name: con},
    )
    if not report.ok:
        raise LedgerBenchError(
            "generator produced an invalid suite (a bug, not your project):\n"
            + "\n".join(report.errors)
        )
    return items, CoverageReport(generated=generated, skipped=skipped)
