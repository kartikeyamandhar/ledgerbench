"""Wire the five axes over traces: the replayable scoring pipeline.

Scoring consumes only what the runner traced plus what the worlds declare
(rulebook registry + grain model + a read-only connection for gold). Nothing
here calls a model except the optional, injected faithfulness judge -- so
re-scoring an old run is exact replay, and the offline demo runs with no judge
at all (axis 5 reads "not evaluated", honestly distinct from agent failures).

(Addition to the section-9 tree, documented in the Phase 6 briefing -- the same
precedent as ``worlds.py`` in ADR-0002: the CLI stays a thin shell over this.)
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from ledgerbench.contracts.item import Item
from ledgerbench.contracts.verdict import AxisResult, Verdict
from ledgerbench.errors import LedgerBenchError
from ledgerbench.gold.compiler import compute_gold
from ledgerbench.registry.definitions import DefinitionRegistry
from ledgerbench.registry.grain_model import GrainModel
from ledgerbench.runner.trace import TraceRecord
from ledgerbench.scorer.actions import score_action
from ledgerbench.scorer.aggregate import roll_up_item
from ledgerbench.scorer.faithfulness import Judge, score_faithfulness
from ledgerbench.scorer.grain_check import check_grain, grain_axis_result
from ledgerbench.scorer.reconcile import reconcile

if TYPE_CHECKING:
    import datetime

    import duckdb

logger = logging.getLogger(__name__)

NO_JUDGE_REASON = "not evaluated: no judge configured (offline run)"


def _malformed_verdict(record: TraceRecord) -> Verdict:
    reason = record.malformed.reason if record.malformed else "missing response"
    axes: dict[Any, AxisResult] = {
        axis: AxisResult(status="fail", evidence={"reason": f"malformed response: {reason}"})
        for axis in ("definitional", "grain", "ambiguity", "refusal", "faithfulness")
    }
    return Verdict(item_id=record.item_id, axes=axes, roll_up="fail")


def score_trace(
    item: Item,
    record: TraceRecord,
    *,
    registry: DefinitionRegistry,
    grain_model: GrainModel,
    con: duckdb.DuckDBPyConnection,
    reference_date: datetime.date,
    judge: Judge | None = None,
) -> Verdict:
    """Score one trace record against its item across all five axes.

    Malformed responses score fail on every axis (the contract). Axes that do
    not apply to an item's class are ``na`` and renormalize in the aggregate.
    """
    if record.response is None:
        return _malformed_verdict(record)
    response = record.response

    axes: dict[Any, AxisResult] = {}

    # Axis 1 -- definitional: only answer-expecting items have gold.
    if item.expected_action == "answer":
        if response.action != "answer":
            axes["definitional"] = AxisResult(
                status="fail",
                evidence={"reason": f"no value to reconcile: agent chose {response.action!r}"},
            )
        else:
            try:
                if item.gold_recipe is not None:
                    definition = registry.get(item.gold_recipe.metric_id)
                    gold = compute_gold(
                        con, definition, item.gold_recipe, reference_date=reference_date
                    )
                    value_type = definition.value_type
                else:
                    assert item.gold_value is not None  # contract: exactly one gold source
                    gold, value_type = item.gold_value, "numeric"
                tolerance = item.tolerance_override
                axes["definitional"] = reconcile(
                    response.value,
                    gold,
                    value_type=value_type,
                    **({"relative_tolerance": tolerance} if tolerance is not None else {}),
                )
            except LedgerBenchError as exc:
                # A defective item/world, not an agent failure: unknown, loudly.
                logger.error("gold computation failed item=%s: %s", item.id, exc)
                axes["definitional"] = AxisResult(
                    status="unknown", evidence={"reason": f"gold computation failed: {exc}"}
                )
    else:
        axes["definitional"] = AxisResult(status="na", evidence={"reason": "no gold expected"})

    # Axis 2 -- grain safety: applies whenever the agent ran SQL for an answer.
    if response.action == "answer" and response.sql:
        axes["grain"] = grain_axis_result(check_grain(response.sql, grain_model))
    else:
        axes["grain"] = AxisResult(status="na", evidence={"reason": "no answer SQL"})

    # Axes 3-4 -- the action matrix, mapped to the axis the item exercises.
    action_result = score_action(
        item.expected_action,
        response,
        ambiguous_term=item.ambiguous_term,
        missing_dimension=item.missing_dimension,
    )
    if item.trap_class == "ambiguity":
        axes["ambiguity"] = action_result
        axes["refusal"] = AxisResult(status="na", evidence={"reason": "not a refusal item"})
    elif item.trap_class == "refusal":
        axes["refusal"] = action_result
        axes["ambiguity"] = AxisResult(status="na", evidence={"reason": "not an ambiguity item"})
    else:
        # Answer-expecting items: over-refusal/deflection lands on the refusal
        # axis (controls exist exactly for this); ambiguity does not apply.
        axes["ambiguity"] = AxisResult(status="na", evidence={"reason": "not an ambiguity item"})
        axes["refusal"] = action_result

    # Axis 5 -- faithfulness: judge optional. Absence is tool-side, so the
    # axis is "na" (not evaluated) rather than "unknown" -- it must not poison
    # the item roll-up the way an agent-caused unknown would (RT-015).
    if judge is None:
        axes["faithfulness"] = AxisResult(
            status="na",
            evidence={
                "reason": NO_JUDGE_REASON if response.assumptions else "no stated assumptions"
            },
        )
    else:
        axes["faithfulness"] = score_faithfulness(response, judge)

    return Verdict(item_id=item.id, axes=axes, roll_up=roll_up_item(axes))


def score_run(
    items: Sequence[Item],
    records: Sequence[TraceRecord],
    *,
    registries: Mapping[str, DefinitionRegistry],
    grain_models: Mapping[str, GrainModel],
    connections: Mapping[str, duckdb.DuckDBPyConnection],
    reference_dates: Mapping[str, datetime.date],
    judge: Judge | None = None,
) -> list[Verdict]:
    """Score every trace record against its item; order follows the traces.

    Raises:
        LedgerBenchError: a trace references an item id not in the suite (the
            run and suite files do not belong together).
    """
    by_id = {item.id: item for item in items}
    verdicts = []
    for record in records:
        item = by_id.get(record.item_id)
        if item is None:
            raise LedgerBenchError(
                f"trace references unknown item {record.item_id!r}; wrong suite file?"
            )
        verdicts.append(
            score_trace(
                item,
                record,
                registry=registries[item.world],
                grain_model=grain_models[item.world],
                con=connections[item.world],
                reference_date=reference_dates[item.world],
                judge=judge,
            )
        )
    return verdicts
