"""Load and validate ``ledgerbench.yaml`` (plus ``.env`` for provider keys).

The config is the contract between a user and a run: which suite, which agent,
which conditions and seeds, the safety/budget rails, the scoring weights, and
the axis thresholds that turn the report into a CI gate. Defaults mirror
``ledgerbench.example.yaml``; unknown keys are rejected loudly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ledgerbench.errors import LedgerBenchError

DEFAULT_WEIGHTS: dict[str, float] = {
    "definitional": 0.30,
    "grain": 0.25,
    "ambiguity": 0.15,
    "refusal": 0.15,
    "faithfulness": 0.15,
}

DEFAULT_THRESHOLDS: dict[str, float] = {
    "definitional": 0.80,
    "grain": 0.80,
    "ambiguity": 0.70,
    "refusal": 0.70,
    "faithfulness": 0.70,
}


class WorldsConfig(BaseModel):
    """World build settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    build_seed: int = 42
    cache_dir: Path = Path(".ledgerbench/worlds")


class AgentConfig(BaseModel):
    """Which adapter to drive, and how."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    adapter: str = "naive"
    model: str | None = None
    endpoint: str | None = None


class RepetitionsConfig(BaseModel):
    """Seeds; each item runs once per seed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seeds: tuple[int, ...] = (11, 22, 33)


class BudgetConfig(BaseModel):
    """Safety and spend rails (see SECURITY.md)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_calls_per_item: int = Field(default=3, ge=1)
    max_usd_per_run: float = Field(default=25.0, ge=0.0)
    statement_timeout_s: float = Field(default=30.0, gt=0)
    row_cap: int = Field(default=100_000, ge=1)


class TolerancesConfig(BaseModel):
    """Reconciliation defaults (ADR-0003)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    relative: float = Field(default=0.005, ge=0.0)
    integer_exact: bool = True


class ReportConfig(BaseModel):
    """Where the rendered report goes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    out: Path = Path("benchmark/results/local/report.html")


class RunConfig(BaseModel):
    """The validated form of ``ledgerbench.yaml``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    suite: Path = Path("benchmark/items/public_v1.jsonl")
    worlds: WorldsConfig = WorldsConfig()
    agent: AgentConfig = AgentConfig()
    conditions: tuple[Literal["closed", "open"], ...] = ("closed", "open")
    repetitions: RepetitionsConfig = RepetitionsConfig()
    budget: BudgetConfig = BudgetConfig()
    tolerances: TolerancesConfig = TolerancesConfig()
    weights: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    thresholds: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))
    report: ReportConfig = ReportConfig()


def load_config(path: str | Path) -> RunConfig:
    """Read and validate a ``ledgerbench.yaml``.

    Raises:
        LedgerBenchError: the file is missing, unreadable, not valid YAML, or
            fails validation -- the message names the offending field.
    """
    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LedgerBenchError(f"cannot read config {config_path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise LedgerBenchError(f"config {config_path} is not valid YAML: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise LedgerBenchError(f"config {config_path} must be a YAML mapping")
    try:
        return RunConfig.model_validate(raw)
    except ValidationError as exc:
        raise LedgerBenchError(f"config {config_path} is invalid: {exc}") from exc
