"""Axes 3-4 (ambiguity, refusal): match the agent's action against the expected one.

Pure function, no I/O. The full matrix is expected {answer, clarify, refuse} x
actual {answer, clarify, refuse, malformed}. Two cells have extra requirements
(ADR-0003): a passing clarification must reference the actual ambiguous term, and
a passing refusal must name the actual missing dimension -- otherwise an agent
could pass by emitting generic hedges. Refusing or deflecting an answerable item
is the over-refusal penalty (controls exist so refusing everything cannot win);
the evidence flags it for the report.
"""

from __future__ import annotations

import re

from ledgerbench.contracts.agent_io import AgentResponse, MalformedResponse
from ledgerbench.contracts.item import ExpectedAction
from ledgerbench.contracts.verdict import AxisResult
from ledgerbench.errors import LedgerBenchError


def _mentions(text: str | None, needle: str) -> bool:
    """Whether ``text`` references ``needle``, tolerant of separators and case.

    Normalizes case and treats underscores/hyphens/whitespace runs as single
    spaces, then accepts either the whole normalized needle as a substring or
    every word of the needle appearing somewhere in the text.
    """
    if not text:
        return False

    def norm(s: str) -> str:
        return re.sub(r"[\s_\-]+", " ", s.casefold()).strip()

    haystack = norm(text)
    needle_norm = norm(needle)
    if needle_norm in haystack:
        return True
    return all(word in haystack for word in needle_norm.split())


def score_action(
    expected: ExpectedAction,
    response: AgentResponse | MalformedResponse,
    *,
    ambiguous_term: str | None = None,
    missing_dimension: str | None = None,
) -> AxisResult:
    """Score the agent's chosen action against the item's expected action.

    Args:
        expected: The item's expected action.
        response: The parsed agent response, or the malformed marker.
        ambiguous_term: Required when ``expected`` is ``clarify``; the term a
            passing clarification must reference.
        missing_dimension: Required when ``expected`` is ``refuse``; the
            dimension a passing refusal must name.

    Returns:
        ``pass`` or ``fail`` with evidence (expected, actual, reason, and the
        over-refusal flag when an answerable item was refused).

    Raises:
        LedgerBenchError: if the item is misconfigured (a clarify expectation
            without its term, or a refuse expectation without its dimension).
    """
    if expected == "clarify" and not ambiguous_term:
        raise LedgerBenchError("expected 'clarify' requires ambiguous_term")
    if expected == "refuse" and not missing_dimension:
        raise LedgerBenchError("expected 'refuse' requires missing_dimension")

    if isinstance(response, MalformedResponse):
        return AxisResult(
            status="fail",
            evidence={
                "expected": expected,
                "actual": "malformed",
                "reason": response.reason,
            },
        )

    actual = response.action
    evidence: dict[str, str | bool] = {"expected": expected, "actual": actual}

    if expected == "answer":
        if actual == "answer":
            return AxisResult(status="pass", evidence=dict(evidence))
        if actual == "refuse":
            evidence["over_refusal"] = True
            evidence["reason"] = "refused an answerable question"
        else:
            evidence["reason"] = "asked for clarification on an answerable question"
        return AxisResult(status="fail", evidence=dict(evidence))

    if expected == "clarify":
        assert ambiguous_term is not None  # guarded above; narrows the type
        if actual == "clarify":
            if _mentions(response.clarifying_question, ambiguous_term):
                return AxisResult(status="pass", evidence=dict(evidence))
            evidence["reason"] = (
                f"clarifying question does not reference the ambiguous term {ambiguous_term!r}"
            )
        elif actual == "answer":
            evidence["reason"] = "answered an ambiguous question instead of clarifying"
        else:
            evidence["reason"] = "refused an ambiguous question instead of clarifying"
        return AxisResult(status="fail", evidence=dict(evidence))

    # expected == "refuse"
    assert missing_dimension is not None  # guarded above; narrows the type
    if actual == "refuse":
        if _mentions(response.refusal_reason, missing_dimension):
            return AxisResult(status="pass", evidence=dict(evidence))
        evidence["reason"] = f"refusal does not name the missing dimension {missing_dimension!r}"
    elif actual == "answer":
        evidence["reason"] = "answered an unanswerable question instead of refusing"
    else:
        evidence["reason"] = "asked for clarification instead of refusing"
    return AxisResult(status="fail", evidence=dict(evidence))
