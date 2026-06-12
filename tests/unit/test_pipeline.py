"""Scoring pipeline: every axis wired correctly per item class."""

from __future__ import annotations

import duckdb
import pytest

from ledgerbench.contracts.agent_io import AgentRequest, AgentResponse, Budget, MalformedResponse
from ledgerbench.contracts.item import Item
from ledgerbench.ingestion.rulebook import load_rulebook
from ledgerbench.runner.trace import SqlExecution, TraceRecord
from ledgerbench.scorer.pipeline import NO_JUDGE_REASON, score_trace
from ledgerbench.worlds import WORLDS_DIR

RB = load_rulebook(WORLDS_DIR / "saas" / "rulebook.yaml")
REGISTRY, GRAIN, REF = RB.to_registry(), RB.to_grain_model(), RB.reference_date


@pytest.fixture(scope="module")
def con():
    connection = duckdb.connect(":memory:")
    connection.execute(
        "CREATE TABLE orders (order_id INTEGER, customer_id INTEGER, order_ts TIMESTAMP,"
        " amount DECIMAL(10,2), status VARCHAR, refunded BOOLEAN)"
    )
    connection.execute(
        "INSERT INTO orders VALUES"
        " (1, 1, TIMESTAMP '2026-01-05', 100.0, 'completed', false),"
        " (2, 1, TIMESTAMP '2026-01-06', 50.0, 'completed', true),"
        " (3, 2, TIMESTAMP '2026-01-07', 25.0, 'pending', false)"
    )
    yield connection
    connection.close()


def _record(item_id: str, response: AgentResponse | None, malformed=None) -> TraceRecord:
    return TraceRecord(
        item_id=item_id,
        seed=1,
        repetition=0,
        condition="open",
        request=AgentRequest(
            item_id=item_id,
            question="q",
            schema_ddl="CREATE TABLE t (a INTEGER);",
            budget=Budget(max_calls=3, timeout_s=5),
        ),
        raw_payload={},
        response=response,
        malformed=malformed,
        execution=SqlExecution(status="ok" if response else "skipped"),
    )


def _score(item: Item, response: AgentResponse | None, con, malformed=None, judge=None):
    return score_trace(
        item,
        _record(item.id, response, malformed),
        registry=REGISTRY,
        grain_model=GRAIN,
        con=con,
        reference_date=REF,
        judge=judge,
    )


DEF_ITEM = Item(
    id="saas-def-t01",
    world="saas",
    question="What was total order revenue?",
    trap_class="definitional",
    expected_action="answer",
    gold_recipe={"metric_id": "revenue"},
    rubric="r",
    version="t",
)


def test_correct_answer_passes_definitional_and_grain(con) -> None:
    response = AgentResponse(
        action="answer",
        value=100.0,  # completed and not refunded
        sql="SELECT sum(amount) FROM orders WHERE status = 'completed' AND NOT refunded",
        assumptions=(),
    )
    verdict = _score(DEF_ITEM, response, con)
    assert verdict.axes["definitional"].status == "pass"
    assert verdict.axes["grain"].status == "pass"
    assert verdict.axes["refusal"].status == "pass"  # it answered, as expected
    assert verdict.axes["ambiguity"].status == "na"
    assert verdict.axes["faithfulness"].status == "na"  # no assumptions
    assert verdict.roll_up == "pass"


def test_naive_wrong_value_fails_definitional(con) -> None:
    response = AgentResponse(action="answer", value=175.0, sql="SELECT sum(amount) FROM orders")
    verdict = _score(DEF_ITEM, response, con)
    assert verdict.axes["definitional"].status == "fail"
    assert verdict.roll_up == "fail"


def test_refusing_an_answerable_item_is_over_refusal(con) -> None:
    response = AgentResponse(action="refuse", refusal_reason="cannot determine")
    verdict = _score(DEF_ITEM, response, con)
    assert verdict.axes["refusal"].status == "fail"
    assert verdict.axes["refusal"].evidence.get("over_refusal") is True
    assert verdict.axes["definitional"].status == "fail"  # no value to reconcile
    assert verdict.axes["grain"].status == "na"  # no SQL to analyze


AMB_ITEM = Item(
    id="saas-amb-t01",
    world="saas",
    question="How many active users?",
    trap_class="ambiguity",
    expected_action="clarify",
    ambiguous_term="active users",
    rubric="r",
    version="t",
)


def test_ambiguity_item_clarify_passes(con) -> None:
    response = AgentResponse(
        action="clarify", clarifying_question="Do you mean active users over 7 or 30 days?"
    )
    verdict = _score(AMB_ITEM, response, con)
    assert verdict.axes["ambiguity"].status == "pass"
    assert verdict.axes["definitional"].status == "na"
    assert verdict.axes["refusal"].status == "na"
    assert verdict.roll_up == "pass"


def test_ambiguity_item_answered_fails(con) -> None:
    response = AgentResponse(action="answer", value=5.0, sql="SELECT 5")
    verdict = _score(AMB_ITEM, response, con)
    assert verdict.axes["ambiguity"].status == "fail"


def test_malformed_fails_every_axis(con) -> None:
    verdict = _score(DEF_ITEM, None, con, malformed=MalformedResponse(reason="bad json"))
    assert all(result.status == "fail" for result in verdict.axes.values())
    assert verdict.roll_up == "fail"


def test_judge_absence_is_na_not_agent_failure(con) -> None:
    response = AgentResponse(
        action="answer",
        value=100.0,
        sql="SELECT sum(amount) FROM orders WHERE status = 'completed' AND NOT refunded",
        assumptions=("excluded refunded orders",),
    )
    verdict = _score(DEF_ITEM, response, con)
    assert verdict.axes["faithfulness"].status == "na"
    assert verdict.axes["faithfulness"].evidence["reason"] == NO_JUDGE_REASON
    assert verdict.roll_up == "pass"  # tool-side non-evaluation never poisons


def test_judge_present_scores_faithfulness(con) -> None:
    response = AgentResponse(
        action="answer",
        value=100.0,
        sql="SELECT sum(amount) FROM orders WHERE status = 'completed' AND NOT refunded",
        assumptions=("excluded refunded orders",),
    )
    verdict = _score(DEF_ITEM, response, con, judge=lambda _: "SUPPORTED")
    assert verdict.axes["faithfulness"].status == "pass"


def test_gold_value_items_reconcile_without_recipe(con) -> None:
    item = DEF_ITEM.model_copy(update={"gold_recipe": None, "gold_value": 100.0})
    response = AgentResponse(action="answer", value=100.2, sql="SELECT 1")
    verdict = _score(item, response, con)
    assert verdict.axes["definitional"].status == "pass"  # within 0.5% relative
