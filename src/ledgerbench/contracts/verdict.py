"""Verdict: per-item, per-axis scorer output with evidence.

Statuses are fail-closed: ``unknown`` (the scorer could not decide) counts
against the agent in axis rates, and ``na`` (the axis does not apply to this
item) is excluded with weight renormalization. Evidence is JSON so reports can
show exactly what was compared without re-running anything.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

Axis = Literal["definitional", "grain", "ambiguity", "refusal", "faithfulness"]
AXES: tuple[Axis, ...] = ("definitional", "grain", "ambiguity", "refusal", "faithfulness")

AxisStatus = Literal["pass", "fail", "na", "unknown"]


class AxisResult(BaseModel):
    """The outcome of one axis for one item, with self-explaining evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: AxisStatus
    evidence: dict[str, JsonValue] = Field(default_factory=dict)


class Verdict(BaseModel):
    """All axis results for one item, plus the item-level roll-up.

    The roll-up is computed by ``scorer.aggregate.roll_up_item`` (fail beats
    unknown beats pass beats na) and stored so traces are self-contained.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str = Field(min_length=1)
    axes: dict[Axis, AxisResult] = Field(min_length=1)
    roll_up: AxisStatus
