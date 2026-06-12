"""Deterministic JSON Schema export for the frozen contracts.

The committed schemas under ``docs/contracts/`` are the public, language-neutral
form of the contract: third-party adapters can validate against them without
importing Python. A golden test re-exports and byte-compares, so any contract
change that forgets the re-export fails CI. Output is deterministic (sorted
keys, two-space indent, trailing newline).
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from ledgerbench.contracts.agent_io import AgentRequest, AgentResponse
from ledgerbench.contracts.item import Item
from ledgerbench.contracts.manifest import RunManifest
from ledgerbench.contracts.verdict import Verdict

EXPORTED_CONTRACTS: tuple[type[BaseModel], ...] = (
    Item,
    AgentRequest,
    AgentResponse,
    Verdict,
    RunManifest,
)


def render_schema(model: type[BaseModel]) -> str:
    """Return one model's JSON Schema as a deterministic string."""
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"


def write_schemas(out_dir: str | Path) -> list[Path]:
    """Write every exported contract's schema into ``out_dir``; return the paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for model in EXPORTED_CONTRACTS:
        path = out / f"{model.__name__}.json"
        path.write_text(render_schema(model), encoding="utf-8")
        written.append(path)
    return written
