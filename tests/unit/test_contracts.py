"""Unit tests for the frozen contracts and the scorer's configuration errors."""

from __future__ import annotations

import datetime
import math

import pytest
from pydantic import ValidationError

from ledgerbench.contracts.agent_io import AgentResponse, MalformedResponse
from ledgerbench.contracts.item import Item
from ledgerbench.contracts.manifest import RunManifest, RunTotals
from ledgerbench.contracts.verdict import AxisResult
from ledgerbench.errors import LedgerBenchError
from ledgerbench.scorer.actions import _mentions, score_action
from ledgerbench.scorer.aggregate import aggregate, roll_up_item
from ledgerbench.scorer.reconcile import reconcile

# --- Item coherence ---------------------------------------------------------


def _item(**overrides) -> dict:
    base = {
        "id": "saas-def-001",
        "world": "saas",
        "question": "What was total revenue?",
        "trap_class": "definitional",
        "expected_action": "answer",
        "gold_recipe": {"metric_id": "revenue"},
        "rubric": "Reconciles to the rulebook revenue metric within tolerance.",
        "version": "public_v1",
    }
    base.update(overrides)
    return base


def test_valid_answer_item() -> None:
    item = Item.model_validate(_item())
    assert item.gold_recipe is not None and item.gold_recipe.metric_id == "revenue"


def test_trap_class_action_mismatch_rejected() -> None:
    with pytest.raises(ValidationError, match="requires expected_action"):
        Item.model_validate(_item(trap_class="ambiguity"))


def test_answer_item_with_both_golds_rejected() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        Item.model_validate(_item(gold_value=10.0))


def test_answer_item_with_no_gold_rejected() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        Item.model_validate(_item(gold_recipe=None))


def test_ambiguity_item_requires_term() -> None:
    with pytest.raises(ValidationError, match="ambiguous_term"):
        Item.model_validate(
            _item(trap_class="ambiguity", expected_action="clarify", gold_recipe=None)
        )


def test_refusal_item_requires_dimension_and_no_gold() -> None:
    item = Item.model_validate(
        _item(
            trap_class="refusal",
            expected_action="refuse",
            gold_recipe=None,
            missing_dimension="cost_center",
        )
    )
    assert item.missing_dimension == "cost_center"
    with pytest.raises(ValidationError, match="must not carry gold"):
        Item.model_validate(
            _item(
                trap_class="refusal",
                expected_action="refuse",
                missing_dimension="cost_center",
            )
        )


# --- RunManifest ------------------------------------------------------------


def _manifest(**overrides) -> RunManifest:
    base = {
        "tool_version": "0.2.0",
        "suite_version": "public_v1",
        "suite_hash": "abc123",
        "world_hashes": {"saas": "deadbeef"},
        "agent_id": "naive",
        "condition": "closed",
        "seeds": (11,),
        "repetitions": 1,
        "totals": RunTotals(items=10, cost_usd=0.0, latency_p50_ms=5.0, latency_p95_ms=9.0),
        "git_commit": "0000000",
        "created_at": datetime.datetime(2026, 6, 12, tzinfo=datetime.UTC),
    }
    base.update(overrides)
    return RunManifest.model_validate(base)


def test_manifest_roundtrip() -> None:
    manifest = _manifest()
    assert manifest.condition == "closed"


def test_manifest_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        _manifest(created_at=datetime.datetime(2026, 6, 12))


# --- Scorer configuration errors (ours, not the agent's) --------------------


def test_reconcile_rejects_non_finite_gold() -> None:
    with pytest.raises(LedgerBenchError, match="finite"):
        reconcile(1.0, math.nan)


def test_reconcile_rejects_negative_tolerance() -> None:
    with pytest.raises(LedgerBenchError, match="tolerance"):
        reconcile(1.0, 1.0, relative_tolerance=-0.1)


def test_reconcile_rejects_fractional_count_gold() -> None:
    with pytest.raises(LedgerBenchError, match="integral"):
        reconcile(1.0, 1.5, value_type="count")


def test_reconcile_fails_on_nan_and_inf_agent_values() -> None:
    assert reconcile(math.nan, 100.0).status == "fail"
    assert reconcile(math.inf, 100.0).status == "fail"


def test_score_action_requires_term_for_clarify() -> None:
    response = AgentResponse(action="clarify", clarifying_question="Which window?")
    with pytest.raises(LedgerBenchError, match="ambiguous_term"):
        score_action("clarify", response)


def test_score_action_requires_dimension_for_refuse() -> None:
    response = AgentResponse(action="refuse", refusal_reason="no such data")
    with pytest.raises(LedgerBenchError, match="missing_dimension"):
        score_action("refuse", response)


def test_mentions_handles_empty_text() -> None:
    assert _mentions(None, "anything") is False
    assert _mentions("", "anything") is False


def test_malformed_response_carries_reason() -> None:
    assert MalformedResponse(reason="x").reason == "x"


# --- Aggregate configuration and roll-up ------------------------------------


def test_aggregate_rejects_bad_weights() -> None:
    with pytest.raises(LedgerBenchError, match="empty"):
        aggregate([], {})
    with pytest.raises(LedgerBenchError, match="finite"):
        aggregate([], {"definitional": -1.0})
    with pytest.raises(LedgerBenchError, match="finite"):
        aggregate([], {"definitional": math.inf})
    with pytest.raises(LedgerBenchError, match="positive"):
        aggregate([], {"definitional": 0.0})


def test_aggregate_empty_verdicts_is_zero() -> None:
    score = aggregate([], {"definitional": 1.0})
    assert score.overall == 0.0
    assert score.per_axis == {}


def test_roll_up_precedence() -> None:
    p = AxisResult(status="pass")
    f = AxisResult(status="fail")
    u = AxisResult(status="unknown")
    n = AxisResult(status="na")
    assert roll_up_item({"definitional": p, "grain": f, "ambiguity": u}) == "fail"
    assert roll_up_item({"definitional": p, "grain": u}) == "unknown"
    assert roll_up_item({"definitional": p, "grain": n}) == "pass"
    assert roll_up_item({"grain": n}) == "na"
