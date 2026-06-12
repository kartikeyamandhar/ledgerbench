"""AgentRequest and AgentResponse: the fixed JSON contract with agents.

Direction matters for strictness. ``AgentRequest`` is produced by the runner, so
unknown fields are a bug and are forbidden. ``AgentResponse`` is produced by the
agent under test and is untrusted: extra fields are ignored, but types and the
action-specific requirements are strict, and anything that fails them is a
``MalformedResponse`` -- which scores zero on every axis for that item.
``parse_agent_response`` never raises on agent data.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

Action = Literal["answer", "clarify", "refuse"]

_MAX_REASON_LEN = 500


class Budget(BaseModel):
    """Per-item budget the adapter must respect."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_calls: int = Field(ge=1)
    timeout_s: float = Field(gt=0)


class AgentRequest(BaseModel):
    """What the runner sends to an adapter for one item."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    schema_ddl: str = Field(min_length=1)
    context_pack: str | None = None  # None in the closed-book condition
    dialect: str = "duckdb"
    budget: Budget


class AgentResponse(BaseModel):
    """What an adapter returns; untrusted until validated.

    Action-specific requirements: ``answer`` needs ``value`` and ``sql``;
    ``clarify`` needs ``clarifying_question``; ``refuse`` needs
    ``refusal_reason``. A response that violates them is malformed.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    action: Action
    value: float | None = None
    sql: str | None = None
    assumptions: tuple[str, ...] = ()
    clarifying_question: str | None = None
    refusal_reason: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _require_action_payload(self) -> AgentResponse:
        """An action without its payload is malformed, not partially scoreable."""
        if self.action == "answer" and (self.value is None or not self.sql):
            raise ValueError("action 'answer' requires both value and sql")
        if self.action == "clarify" and not self.clarifying_question:
            raise ValueError("action 'clarify' requires clarifying_question")
        if self.action == "refuse" and not self.refusal_reason:
            raise ValueError("action 'refuse' requires refusal_reason")
        return self


class MalformedResponse(BaseModel):
    """Why an agent payload could not be accepted; scores zero on all axes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str = Field(min_length=1)


def parse_agent_response(payload: object) -> AgentResponse | MalformedResponse:
    """Validate an untrusted agent payload; never raise.

    Accepts a JSON string/bytes or an already-decoded object. Anything that is
    not a JSON object satisfying :class:`AgentResponse` comes back as a
    :class:`MalformedResponse` carrying the reason (truncated, for traces).
    """
    data: object = payload
    if isinstance(payload, str | bytes):
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return MalformedResponse(reason=f"not valid JSON: {exc}"[:_MAX_REASON_LEN])

    if not isinstance(data, dict):
        kind = type(data).__name__
        return MalformedResponse(reason=f"expected a JSON object, got {kind}")

    try:
        return AgentResponse.model_validate(data)
    except ValidationError as exc:
        return MalformedResponse(reason=f"schema violation: {exc}"[:_MAX_REASON_LEN])
