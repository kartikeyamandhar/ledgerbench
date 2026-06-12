"""Item: one exam question with trap metadata, gold recipe, and rubric.

An item is data, not code. Gold is either a recipe (a rulebook metric id plus
parameters, re-derived mechanically whenever worlds or tolerances change) or a
literal value for hand-computed cases; never both. Validators enforce the
taxonomy's internal coherence so a malformed item fails at load time, not at
scoring time.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

TrapClass = Literal["definitional", "grain", "ambiguity", "refusal", "period", "control"]
ExpectedAction = Literal["answer", "clarify", "refuse"]

_EXPECTED_BY_CLASS: dict[str, str] = {
    "definitional": "answer",
    "grain": "answer",
    "period": "answer",
    "control": "answer",
    "ambiguity": "clarify",
    "refusal": "refuse",
}


class GoldRecipe(BaseModel):
    """How to recompute an item's gold from the rulebook: metric id plus params."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric_id: str = Field(min_length=1)
    params: dict[str, JsonValue] = Field(default_factory=dict)


class Item(BaseModel):
    """One benchmark question with everything needed to grade it mechanically.

    ``ambiguous_term`` and ``missing_dimension`` exist so the action scorer can
    check *mechanically* that a clarification references the actual ambiguous
    term and a refusal names the actual missing dimension (see ADR-0003).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    world: str = Field(min_length=1)
    question: str = Field(min_length=1)
    trap_class: TrapClass
    expected_action: ExpectedAction
    gold_recipe: GoldRecipe | None = None
    gold_value: float | None = None
    declared_grain: tuple[str, ...] | None = None
    tolerance_override: float | None = Field(default=None, ge=0.0)
    ambiguous_term: str | None = None
    missing_dimension: str | None = None
    rubric: str = Field(min_length=1)
    version: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check_coherence(self) -> Item:
        """Enforce taxonomy coherence and exactly one gold source for answers."""
        required = _EXPECTED_BY_CLASS[self.trap_class]
        if self.expected_action != required:
            raise ValueError(
                f"trap_class {self.trap_class!r} requires expected_action {required!r}, "
                f"got {self.expected_action!r}"
            )

        if self.expected_action == "answer":
            if (self.gold_recipe is None) == (self.gold_value is None):
                raise ValueError("answer items need exactly one of gold_recipe or gold_value")
        elif self.gold_recipe is not None or self.gold_value is not None:
            raise ValueError("clarify/refuse items must not carry gold")

        if self.trap_class == "ambiguity" and not self.ambiguous_term:
            raise ValueError("ambiguity items must declare ambiguous_term")
        if self.trap_class == "refusal" and not self.missing_dimension:
            raise ValueError("refusal items must declare missing_dimension")
        return self
