"""Faithfulness axis: extractors, double-run discipline, caching, axis paths."""

from __future__ import annotations

from ledgerbench.contracts.agent_io import AgentResponse
from ledgerbench.scorer.faithfulness import (
    CachingJudge,
    extract_sql_facts,
    judge_assumption,
    score_faithfulness,
)

REVENUE_SQL = (
    "SELECT sum(amount) FROM orders WHERE status = 'completed' AND NOT refunded "
    "AND order_ts >= TIMESTAMP '2026-03-01'"
)


def test_extractor_surfaces_filters_exclusions_and_dates() -> None:
    facts = extract_sql_facts(REVENUE_SQL)
    assert facts is not None
    assert facts.tables == ("orders",)
    assert any("'completed'" in f for f in facts.filters)
    assert any("refunded" in x for x in facts.exclusions)
    assert any("2026-03-01" in d for d in facts.date_bounds)
    assert facts.aggregates == ("SUM(amount)",)


def test_extractor_surfaces_joins() -> None:
    facts = extract_sql_facts(
        "SELECT sum(o.amount) FROM orders o JOIN customers c ON o.customer_id = c.customer_id"
    )
    assert facts is not None
    assert facts.tables == ("customers", "orders")
    assert facts.joins and "customer_id" in facts.joins[0]


def test_extractor_returns_none_on_garbage() -> None:
    assert extract_sql_facts("not sql at all (((") is None
    assert extract_sql_facts("UPDATE orders SET amount = 0") is None


def test_double_run_agreement_required() -> None:
    facts = extract_sql_facts(REVENUE_SQL)
    assert facts is not None

    flipper = iter(["SUPPORTED", "CONTRADICTED"])
    assert judge_assumption("x", facts, lambda _: next(flipper)) == "unknown"
    assert judge_assumption("x", facts, lambda _: "SUPPORTED") == "supported"
    assert judge_assumption("x", facts, lambda _: "no idea, sorry") == "unknown"


def test_caching_judge_calls_underlying_once_per_prompt(tmp_path) -> None:
    calls: list[str] = []

    def judge(prompt: str) -> str:
        calls.append(prompt)
        return "SUPPORTED"

    cached = CachingJudge(judge, cache_dir=tmp_path)
    facts = extract_sql_facts(REVENUE_SQL)
    assert facts is not None
    judge_assumption("excluded refunds", facts, cached)
    judge_assumption("excluded refunds", facts, cached)
    assert len(calls) == 2  # the double-run's two distinct prompts, cached after

    # A fresh CachingJudge over the same disk cache makes zero new calls.
    cached2 = CachingJudge(judge, cache_dir=tmp_path)
    judge_assumption("excluded refunds", facts, cached2)
    assert len(calls) == 2


def _response(assumptions: tuple[str, ...], sql: str | None = REVENUE_SQL) -> AgentResponse:
    return AgentResponse(action="answer", value=1.0, sql=sql, assumptions=assumptions)


def test_no_assumptions_is_na_and_judge_never_runs() -> None:
    def exploding_judge(prompt: str) -> str:
        raise AssertionError("judge must not run without assumptions")

    result = score_faithfulness(_response(()), exploding_judge)
    assert result.status == "na"


def test_assumptions_without_parseable_sql_fail() -> None:
    result = score_faithfulness(
        AgentResponse(action="refuse", refusal_reason="x", assumptions=("claimed thing",)),
        lambda _: "SUPPORTED",
    )
    assert result.status == "fail"


def test_contradicted_assumption_fails_and_is_named() -> None:
    result = score_faithfulness(_response(("excluded refunds",)), lambda _: "CONTRADICTED")
    assert result.status == "fail"
    assert result.evidence["contradicted"] == ["excluded refunds"]


def test_all_supported_passes_with_versioned_prompt() -> None:
    result = score_faithfulness(
        _response(("excluded refunds", "march only")), lambda _: "SUPPORTED"
    )
    assert result.status == "pass"
    assert result.evidence["judge_prompt_version"] == "faithfulness-judge-v1"


def test_disagreement_bubbles_to_unknown() -> None:
    replies = iter(["SUPPORTED", "UNRELATED"])
    result = score_faithfulness(_response(("one claim",)), lambda _: next(replies))
    assert result.status == "unknown"
