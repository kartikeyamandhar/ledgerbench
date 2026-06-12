"""Axis 1 (definitional): reconcile the agent's value to gold within tolerance.

Pure function, no I/O. The rules (ADR-0003): ``numeric`` metrics reconcile within
a *relative* tolerance (default 0.5%, per-item override); ``count`` metrics are
integer cardinalities and must match exactly; a gold of exactly zero requires an
agent value of exactly zero, because relative tolerance is undefined at zero
(fail closed). Agent input never raises -- a missing or non-finite value is a
``fail`` with evidence. Raising is reserved for *our* bugs (bad gold, bad
tolerance), which are configuration errors, not scores.
"""

from __future__ import annotations

import math

from ledgerbench.contracts.verdict import AxisResult
from ledgerbench.errors import LedgerBenchError
from ledgerbench.registry.definitions import ValueType

DEFAULT_RELATIVE_TOLERANCE = 0.005
"""Default relative tolerance for numeric reconciliation (0.5%)."""


def reconcile(
    agent_value: float | None,
    gold_value: float,
    *,
    value_type: ValueType = "numeric",
    relative_tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
) -> AxisResult:
    """Compare an agent's value to gold and return the definitional axis result.

    Args:
        agent_value: The value the agent answered with, or None if absent.
        gold_value: The true value, derived mechanically from the rulebook.
        value_type: ``numeric`` (relative tolerance) or ``count`` (exact).
        relative_tolerance: Per-item relative tolerance for numeric metrics.

    Returns:
        ``pass`` or ``fail`` with evidence showing exactly what was compared.

    Raises:
        LedgerBenchError: if gold is non-finite, a count gold is non-integral,
            or the tolerance is negative -- these are our bugs, never the agent's.
    """
    if not math.isfinite(gold_value):
        raise LedgerBenchError(f"gold_value must be finite, got {gold_value!r}")
    if relative_tolerance < 0:
        raise LedgerBenchError(f"relative_tolerance must be >= 0, got {relative_tolerance!r}")
    if value_type == "count" and gold_value != int(gold_value):
        raise LedgerBenchError(f"count gold must be integral, got {gold_value!r}")

    if agent_value is None:
        return AxisResult(
            status="fail",
            evidence={"rule": "missing_value", "gold_value": gold_value},
        )
    if not math.isfinite(agent_value):
        return AxisResult(
            status="fail",
            evidence={
                "rule": "non_finite_value",
                "agent_value": repr(agent_value),
                "gold_value": gold_value,
            },
        )

    if value_type == "count":
        passed = agent_value == gold_value
        return AxisResult(
            status="pass" if passed else "fail",
            evidence={
                "rule": "exact_count",
                "agent_value": agent_value,
                "gold_value": gold_value,
            },
        )

    if gold_value == 0:
        passed = agent_value == 0
        return AxisResult(
            status="pass" if passed else "fail",
            evidence={
                "rule": "zero_gold_exact",
                "agent_value": agent_value,
                "gold_value": gold_value,
            },
        )

    relative_diff = abs(agent_value - gold_value) / abs(gold_value)
    passed = relative_diff <= relative_tolerance
    return AxisResult(
        status="pass" if passed else "fail",
        evidence={
            "rule": "relative_tolerance",
            "agent_value": agent_value,
            "gold_value": gold_value,
            "relative_diff": relative_diff,
            "tolerance": relative_tolerance,
        },
    )
