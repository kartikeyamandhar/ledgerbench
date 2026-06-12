"""Property-based tests for the scorer core (hypothesis)."""

from __future__ import annotations

import math

from hypothesis import given
from hypothesis import strategies as st

from ledgerbench.contracts.agent_io import (
    AgentResponse,
    MalformedResponse,
    parse_agent_response,
)
from ledgerbench.contracts.verdict import AXES, AxisResult, Verdict
from ledgerbench.scorer.aggregate import aggregate, roll_up_item
from ledgerbench.scorer.reconcile import reconcile

# Gold values away from zero, scales away from float extremes.
golds = st.floats(min_value=1e-3, max_value=1e9).filter(lambda g: g != 0)
scales = st.floats(min_value=1e-3, max_value=1e3)
rel_errors = st.floats(min_value=0.0, max_value=0.1)


@given(gold=golds, rel_err=rel_errors, scale=scales, sign=st.sampled_from([-1.0, 1.0]))
def test_reconciliation_is_scale_invariant(
    gold: float, rel_err: float, scale: float, sign: float
) -> None:
    # Skip values within fp-noise of the tolerance boundary; scaling cannot
    # be expected to preserve an exact boundary tie.
    if math.isclose(rel_err, 0.005, abs_tol=1e-9):
        return
    agent = gold * (1.0 + sign * rel_err)
    before = reconcile(agent, gold).status
    after = reconcile(agent * scale, gold * scale).status
    assert before == after


@given(
    gold=golds,
    rel_err=rel_errors,
    t1=st.floats(min_value=0.0, max_value=0.5),
    extra=st.floats(min_value=0.0, max_value=0.5),
)
def test_tolerance_is_monotonic(gold: float, rel_err: float, t1: float, extra: float) -> None:
    agent = gold * (1.0 + rel_err)
    t2 = t1 + extra
    if reconcile(agent, gold, relative_tolerance=t1).status == "pass":
        assert reconcile(agent, gold, relative_tolerance=t2).status == "pass"


statuses = st.sampled_from(["pass", "fail", "na", "unknown"])
verdict_axes = st.dictionaries(st.sampled_from(AXES), statuses, min_size=1, max_size=5)


@given(
    axes_specs=st.lists(verdict_axes, min_size=0, max_size=30),
    weights=st.dictionaries(
        st.sampled_from(AXES),
        st.floats(min_value=0.0, max_value=10.0),
        min_size=1,
        max_size=5,
    ).filter(lambda w: sum(w.values()) > 0),
)
def test_aggregate_is_bounded(axes_specs: list[dict], weights: dict) -> None:
    verdicts = []
    for i, spec in enumerate(axes_specs):
        axes = {axis: AxisResult(status=status) for axis, status in spec.items()}
        verdicts.append(Verdict(item_id=f"i{i}", axes=axes, roll_up=roll_up_item(axes)))
    score = aggregate(verdicts, weights)
    assert 0.0 <= score.overall <= 1.0
    for axis_score in score.per_axis.values():
        assert 0.0 <= axis_score.rate <= 1.0


json_like = st.recursive(
    st.none() | st.booleans() | st.floats(allow_nan=False) | st.integers() | st.text(max_size=20),
    lambda children: (
        st.lists(children, max_size=5) | st.dictionaries(st.text(max_size=10), children, max_size=5)
    ),
    max_leaves=20,
)


@given(payload=json_like | st.text(max_size=200) | st.binary(max_size=200))
def test_parse_agent_response_never_raises(payload: object) -> None:
    result = parse_agent_response(payload)
    assert isinstance(result, AgentResponse | MalformedResponse)
