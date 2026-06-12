"""Pydantic data contracts; the dependency sink every module points inward to.

Frozen as of Phase 2: changes require an ADR, a JSON Schema re-export, and a
minor version bump.
"""

from ledgerbench.contracts.agent_io import (
    AgentRequest,
    AgentResponse,
    Budget,
    MalformedResponse,
    parse_agent_response,
)
from ledgerbench.contracts.item import GoldRecipe, Item
from ledgerbench.contracts.manifest import RunManifest, RunTotals
from ledgerbench.contracts.verdict import AXES, AxisResult, Verdict

__all__ = [
    "AXES",
    "AgentRequest",
    "AgentResponse",
    "AxisResult",
    "Budget",
    "GoldRecipe",
    "Item",
    "MalformedResponse",
    "RunManifest",
    "RunTotals",
    "Verdict",
    "parse_agent_response",
]
