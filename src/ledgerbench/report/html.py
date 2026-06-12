"""Render the single-file offline report and evaluate the threshold gate.

One template, one output file, inline SVG, no JavaScript required, autoescape
on (agent SQL is escaped text -- XSS-safe by construction). The renderer also
evaluates the axis thresholds and returns the breaches, which is what gives the
CLI its CI-gate exit code.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from ledgerbench.contracts.item import Item
from ledgerbench.contracts.manifest import RunManifest
from ledgerbench.contracts.verdict import Verdict
from ledgerbench.gold.compiler import compile_recipe
from ledgerbench.registry.definitions import DefinitionRegistry
from ledgerbench.report.charts import axis_chart, condition_chart, gap_chart
from ledgerbench.runner.trace import TraceRecord
from ledgerbench.scorer.aggregate import aggregate
from ledgerbench.scorer.pipeline import NO_JUDGE_REASON

_ENV = Environment(
    loader=PackageLoader("ledgerbench.report", "templates"),
    autoescape=select_autoescape(default=True, default_for_string=True),
)


@dataclass(frozen=True)
class AxisRow:
    """One row of the per-axis table."""

    passed: int
    failed: int
    unknown: int
    na: int
    rate: float
    weight: float
    threshold: float
    met: bool


@dataclass(frozen=True)
class FailureEntry:
    """One failure-gallery card."""

    item_id: str
    trap_class: str
    question: str
    reason: str
    agent_sql: str | None
    gold_sql: str | None
    evidence: dict[str, str]
    statuses: dict[str, str]


@dataclass(frozen=True)
class ReportResult:
    """What the CLI needs after rendering: the file and the gate outcome."""

    path: Path
    overall: float
    breaches: tuple[str, ...] = ()
    size_bytes: int = 0
    extra: dict[str, float] = field(default_factory=dict)


def _evidence_line(evidence: Mapping[str, object]) -> str:
    parts = []
    for key, value in evidence.items():
        if value in (None, [], {}, ()):
            continue
        rendered = str(value)
        if len(rendered) > 220:
            rendered = rendered[:220] + "…"
        parts.append(f"{key}: {rendered}")
    return "; ".join(parts) or "(no evidence)"


def _failure_entries(
    items_by_id: Mapping[str, Item],
    records: Sequence[TraceRecord],
    verdicts: Sequence[Verdict],
    registries: Mapping[str, DefinitionRegistry],
    reference_dates: Mapping[str, object],
) -> list[FailureEntry]:
    records_by_key: dict[str, TraceRecord] = {}
    for record in records:
        if record.item_id not in records_by_key:
            records_by_key[record.item_id] = record  # first repetition shown

    entries = []
    for verdict in verdicts:
        if verdict.roll_up != "fail":
            continue
        item = items_by_id[verdict.item_id]
        shown = records_by_key.get(verdict.item_id)
        failing = [
            (axis, result) for axis, result in verdict.axes.items() if result.status == "fail"
        ]
        reason = str(failing[0][1].evidence.get("reason", failing[0][0])) if failing else "failed"
        gold_sql = None
        if item.gold_recipe is not None:
            definition = registries[item.world].get(item.gold_recipe.metric_id)
            gold_sql = compile_recipe(
                definition,
                item.gold_recipe,
                reference_date=reference_dates[item.world],  # type: ignore[arg-type]
            )
        entries.append(
            FailureEntry(
                item_id=item.id,
                trap_class=item.trap_class,
                question=item.question,
                reason=reason,
                agent_sql=(shown.response.sql if shown and shown.response else None),
                gold_sql=gold_sql,
                evidence={a: _evidence_line(r.evidence) for a, r in verdict.axes.items()},
                statuses={a: r.status for a, r in verdict.axes.items()},
            )
        )
    return entries


def render_report(
    items: Sequence[Item],
    records: Sequence[TraceRecord],
    verdicts: Sequence[Verdict],
    manifest: RunManifest,
    *,
    registries: Mapping[str, DefinitionRegistry],
    reference_dates: Mapping[str, object],
    weights: Mapping[str, float],
    thresholds: Mapping[str, float],
    judge_configured: bool,
    out_path: str | Path,
    comparison: tuple[Mapping[str, float], Mapping[str, float]] | None = None,
) -> ReportResult:
    """Render the report file and evaluate the threshold gate.

    When no judge is configured, faithfulness is shown but excluded from both
    the weighted overall and the gate (its unknowns are tool-side; RT-015).
    """
    items_by_id = {item.id: item for item in items}

    effective_weights = dict(weights)
    effective_thresholds = dict(thresholds)
    if not judge_configured:
        effective_weights.pop("faithfulness", None)
        effective_thresholds.pop("faithfulness", None)

    score = aggregate(list(verdicts), effective_weights)

    answered = [r for r in records if r.response is not None and r.response.action == "answer"]
    ran_fine = (
        sum(r.execution.status == "ok" for r in answered) / len(answered) if answered else 0.0
    )
    by_item_pass = {v.item_id: v.roll_up == "pass" for v in verdicts}
    business_correct = sum(by_item_pass.values()) / len(by_item_pass) if by_item_pass else 0.0

    axis_rows: dict[str, AxisRow] = {}
    breaches: list[str] = []
    for axis, axis_score in score.per_axis.items():
        threshold = effective_thresholds.get(axis)
        met = True if threshold is None else axis_score.rate >= threshold
        applicable = axis_score.passed + axis_score.failed + axis_score.unknown
        if threshold is not None and applicable > 0 and not met:
            breaches.append(axis)
        axis_rows[axis] = AxisRow(
            passed=axis_score.passed,
            failed=axis_score.failed,
            unknown=axis_score.unknown,
            na=axis_score.na,
            rate=axis_score.rate,
            weight=effective_weights.get(axis, 0.0),
            threshold=threshold if threshold is not None else 0.0,
            met=met,
        )

    no_judge_note = not judge_configured and any(
        r.evidence.get("reason") == NO_JUDGE_REASON for v in verdicts for r in v.axes.values()
    )

    html = _ENV.get_template("report.html.j2").render(
        manifest=manifest,
        gap_svg=gap_chart(ran_fine, business_correct),
        axis_svg=axis_chart({a: row.rate for a, row in axis_rows.items()}),
        condition_svg=(condition_chart(comparison[0], comparison[1]) if comparison else None),
        axis_rows=axis_rows,
        overall=score.overall,
        no_judge_note=no_judge_note,
        failures=_failure_entries(items_by_id, records, verdicts, registries, reference_dates),
    )

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return ReportResult(
        path=out,
        overall=score.overall,
        breaches=tuple(breaches),
        size_bytes=out.stat().st_size,
        extra={"ran_fine": ran_fine, "business_correct": business_correct},
    )
