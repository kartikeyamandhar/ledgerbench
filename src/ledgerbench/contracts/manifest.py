"""RunManifest: the full reproducibility record for one benchmark run.

Every number the leaderboard or report shows must be traceable to a committed
manifest: which suite (by version and hash), which worlds (by content digest),
which agent and model snapshot, which condition and seeds, what it cost, and the
exact tool commit. Manifests are emitted by the runner (Phase 4) and consumed by
the report and the leaderboard.
"""

from __future__ import annotations

import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Condition = Literal["closed", "open"]


class RunTotals(BaseModel):
    """Run-level accounting: size, spend, and latency."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: int = Field(ge=0)
    cost_usd: float = Field(ge=0.0)
    latency_p50_ms: float = Field(ge=0.0)
    latency_p95_ms: float = Field(ge=0.0)


class RunManifest(BaseModel):
    """Everything needed to attribute, audit, and re-score one run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_version: str = Field(min_length=1)
    suite_version: str = Field(min_length=1)
    suite_hash: str = Field(min_length=1)
    world_hashes: dict[str, str]
    agent_id: str = Field(min_length=1)
    model_snapshot_id: str | None = None
    condition: Condition
    seeds: tuple[int, ...] = Field(min_length=1)
    repetitions: int = Field(ge=1)
    totals: RunTotals
    git_commit: str = Field(min_length=1)
    created_at: datetime.datetime

    @field_validator("created_at")
    @classmethod
    def _require_timezone(cls, value: datetime.datetime) -> datetime.datetime:
        """Naive timestamps are ambiguous across machines; require tz-aware."""
        if value.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return value
