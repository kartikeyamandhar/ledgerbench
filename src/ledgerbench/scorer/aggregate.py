"""Weighted roll-up of axis results into item and suite scores.

Pure functions, no I/O. Fail-closed semantics (ADR-0003): ``unknown`` counts
against the agent in axis pass rates; ``na`` axes are excluded and the weights
renormalize over the axes that actually applied. Weights come from config and
are echoed in the output so every report prints them.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from ledgerbench.contracts.verdict import AxisResult, AxisStatus, Verdict
from ledgerbench.errors import LedgerBenchError

Axis = str  # keys validated against contracts.verdict.AXES by the weights check


class AxisScore(BaseModel):
    """Counts and pass rate for one axis across a suite."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    unknown: int = Field(ge=0)
    na: int = Field(ge=0)
    rate: float = Field(ge=0.0, le=1.0)


class SuiteScore(BaseModel):
    """Per-axis scores plus the weighted overall, with the weights echoed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    per_axis: dict[str, AxisScore]
    weights: dict[str, float]
    overall: float = Field(ge=0.0, le=1.0)


def roll_up_item(axes: Mapping[str, AxisResult]) -> AxisStatus:
    """Collapse one item's axis results: fail beats unknown beats pass beats na."""
    statuses = {result.status for result in axes.values()}
    if "fail" in statuses:
        return "fail"
    if "unknown" in statuses:
        return "unknown"
    if "pass" in statuses:
        return "pass"
    return "na"


def _validate_weights(weights: Mapping[str, float]) -> None:
    """Reject weight configs that would silently distort the overall score."""
    if not weights:
        raise LedgerBenchError("weights must not be empty")
    for axis, weight in weights.items():
        if not math.isfinite(weight) or weight < 0:
            raise LedgerBenchError(f"weight for {axis!r} must be finite and >= 0, got {weight!r}")
    if sum(weights.values()) <= 0:
        raise LedgerBenchError("at least one weight must be positive")


def aggregate(verdicts: Sequence[Verdict], weights: Mapping[str, float]) -> SuiteScore:
    """Roll a suite of verdicts up into per-axis rates and a weighted overall.

    An axis's rate is ``passed / (passed + failed + unknown)`` -- ``unknown``
    counts against, ``na`` does not count at all. The overall is the
    weight-normalized mean of rates over axes that were applicable to at least
    one item; axes that never applied contribute nothing. No applicable axes
    (or no verdicts) yields an overall of 0.0, never a crash.

    Raises:
        LedgerBenchError: if the weights are empty, negative, or all zero.
    """
    _validate_weights(weights)

    counts: dict[str, dict[str, int]] = {}
    for verdict in verdicts:
        for verdict_axis, result in verdict.axes.items():
            axis_counts = counts.setdefault(
                verdict_axis, {"pass": 0, "fail": 0, "unknown": 0, "na": 0}
            )
            axis_counts[result.status] += 1

    per_axis: dict[str, AxisScore] = {}
    for axis, c in sorted(counts.items()):
        applicable = c["pass"] + c["fail"] + c["unknown"]
        rate = c["pass"] / applicable if applicable else 0.0
        per_axis[axis] = AxisScore(
            passed=c["pass"], failed=c["fail"], unknown=c["unknown"], na=c["na"], rate=rate
        )

    weighted_sum = 0.0
    weight_total = 0.0
    for axis, score in per_axis.items():
        weight = weights.get(axis, 0.0)
        if score.passed + score.failed + score.unknown == 0:
            continue  # axis never applied; exclude from normalization
        weighted_sum += weight * score.rate
        weight_total += weight

    overall = weighted_sum / weight_total if weight_total > 0 else 0.0
    return SuiteScore(per_axis=per_axis, weights=dict(weights), overall=overall)
