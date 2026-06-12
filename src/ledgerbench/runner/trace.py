"""Per-item JSONL traces: the only interface between execution and scoring.

A trace record is the *deterministic* evidence of one item attempt: the request
sent, the raw payload returned, how it parsed, what SQL was executed and what it
returned. Deliberately absent: timestamps, latencies, and cost -- volatile data
belongs to the RunManifest. Same seed + same offline adapter must produce
byte-identical trace files (asserted in tests), which is what makes re-scoring
old runs and counterfactual replay trustworthy.

Serialization is canonical: sorted keys, compact separators, one record per
line, newline-terminated.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from ledgerbench.contracts.agent_io import AgentRequest, AgentResponse, MalformedResponse


class SqlExecution(BaseModel):
    """What happened when the agent's SQL went through the safety gate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["ok", "blocked", "error", "skipped"]
    vetted_sql: str | None = None
    value: float | None = None  # first column of the first row, when scalar-like
    row_count: int | None = None
    error: str | None = None


class TraceRecord(BaseModel):
    """One item attempt, reproducibly. No wall-clock anywhere."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str = Field(min_length=1)
    seed: int
    repetition: int = Field(ge=0)
    condition: Literal["closed", "open"]
    request: AgentRequest
    raw_payload: JsonValue
    response: AgentResponse | None = None
    malformed: MalformedResponse | None = None
    execution: SqlExecution
    adapter_sql_calls: tuple[str, ...] = ()


def trace_line(record: TraceRecord) -> str:
    """Render one record as a canonical JSONL line (sorted keys, compact)."""
    payload = record.model_dump(mode="json")
    return json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"


class TraceWriter:
    """Streaming JSONL writer; records are flushed as they happen, not buffered."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w", encoding="utf-8")
        self.count = 0

    def write(self, record: TraceRecord) -> None:
        """Append one record and flush so partial runs leave usable traces."""
        self._handle.write(trace_line(record))
        self._handle.flush()
        self.count += 1

    def close(self) -> None:
        """Close the underlying file handle."""
        self._handle.close()

    def __enter__(self) -> TraceWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def read_traces(path: str | Path) -> Iterator[TraceRecord]:
    """Stream trace records back from a JSONL file (``.gz`` transparently).

    Committed benchmark results are gzipped (the open-book context pack rides
    in every request and compresses ~50x); local runs stay plain JSONL.
    """
    trace_path = Path(path)
    if trace_path.suffix == ".gz":
        import gzip

        with gzip.open(trace_path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield TraceRecord.model_validate_json(line)
        return
    with trace_path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield TraceRecord.model_validate_json(line)
