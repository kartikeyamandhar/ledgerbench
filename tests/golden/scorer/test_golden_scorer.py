"""Golden suite: the hand-verified fixtures that validate the validator.

Every case in the YAML files was worked out by hand. The suite must stay at
25+ cases (enforced below); additions are welcome, silent edits are not.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from ledgerbench.contracts.agent_io import (
    AgentResponse,
    MalformedResponse,
    parse_agent_response,
)
from ledgerbench.contracts.verdict import AxisResult, Verdict
from ledgerbench.scorer.actions import score_action
from ledgerbench.scorer.aggregate import aggregate, roll_up_item
from ledgerbench.scorer.reconcile import DEFAULT_RELATIVE_TOLERANCE, reconcile

_DIR = Path(__file__).parent

MALFORMED_SENTINEL = MalformedResponse(reason="golden fixture: malformed payload")


def _load(name: str) -> list[dict]:
    cases = yaml.safe_load((_DIR / name).read_text(encoding="utf-8"))
    assert isinstance(cases, list) and cases, f"{name} must be a non-empty list"
    return cases


RECONCILE_CASES = _load("reconcile_cases.yaml")
ACTION_CASES = _load("action_cases.yaml")
MALFORMED_CASES = _load("malformed_cases.yaml")
AGGREGATE_CASES = _load("aggregate_cases.yaml")


def test_golden_suite_has_at_least_25_cases() -> None:
    total = len(RECONCILE_CASES) + len(ACTION_CASES) + len(MALFORMED_CASES) + len(AGGREGATE_CASES)
    assert total >= 25, f"golden suite shrank to {total} cases; it must stay >= 25"


@pytest.mark.parametrize("case", RECONCILE_CASES, ids=lambda c: c["name"])
def test_reconcile_golden(case: dict) -> None:
    result = reconcile(
        case["agent_value"],
        case["gold_value"],
        value_type=case.get("value_type", "numeric"),
        relative_tolerance=case.get("tolerance", DEFAULT_RELATIVE_TOLERANCE),
    )
    assert result.status == case["expect"], f"{case['name']}: evidence={result.evidence}"


@pytest.mark.parametrize("case", ACTION_CASES, ids=lambda c: c["name"])
def test_action_golden(case: dict) -> None:
    raw = case["response"]
    response: AgentResponse | MalformedResponse
    if raw == "malformed":
        response = MALFORMED_SENTINEL
    else:
        parsed = parse_agent_response(raw)
        assert isinstance(parsed, AgentResponse), f"fixture response invalid: {parsed}"
        response = parsed

    result = score_action(
        case["expected"],
        response,
        ambiguous_term=case.get("ambiguous_term"),
        missing_dimension=case.get("missing_dimension"),
    )
    assert result.status == case["expect"], f"{case['name']}: evidence={result.evidence}"
    if case.get("over_refusal"):
        assert result.evidence.get("over_refusal") is True


@pytest.mark.parametrize("case", MALFORMED_CASES, ids=lambda c: c["name"])
def test_malformed_golden(case: dict) -> None:
    result = parse_agent_response(case["payload"])
    if case["malformed"]:
        assert isinstance(result, MalformedResponse), f"{case['name']}: parsed as {result!r}"
        assert result.reason
    else:
        assert isinstance(result, AgentResponse), f"{case['name']}: rejected: {result!r}"


@pytest.mark.parametrize("case", AGGREGATE_CASES, ids=lambda c: c["name"])
def test_aggregate_golden(case: dict) -> None:
    verdicts = []
    for i, axes_spec in enumerate(case["verdicts"]):
        axes = {axis: AxisResult(status=status) for axis, status in axes_spec.items()}
        verdicts.append(Verdict(item_id=f"item-{i}", axes=axes, roll_up=roll_up_item(axes)))
    score = aggregate(verdicts, case["weights"])
    assert math.isclose(score.overall, case["expect_overall"], abs_tol=1e-12), (
        f"{case['name']}: got {score.overall}, per_axis={score.per_axis}"
    )
    assert score.weights == case["weights"]  # weights echoed for the report
