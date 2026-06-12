"""Report rendering: XSS safety, gate evaluation, chart output."""

from __future__ import annotations

import datetime

from ledgerbench.contracts.agent_io import AgentRequest, AgentResponse, Budget
from ledgerbench.contracts.item import Item
from ledgerbench.contracts.manifest import RunManifest, RunTotals
from ledgerbench.contracts.verdict import AxisResult, Verdict
from ledgerbench.report.charts import axis_chart, gap_chart
from ledgerbench.report.html import render_report
from ledgerbench.runner.trace import SqlExecution, TraceRecord

EVIL_SQL = "SELECT 1 -- <script>alert('xss')</script>"


def _fixture(tmp_path):
    item = Item(
        id="saas-def-x01",
        world="saas",
        question="Total <b>revenue</b>?",
        trap_class="definitional",
        expected_action="answer",
        gold_value=100.0,
        rubric="r",
        version="t",
    )
    response = AgentResponse(action="answer", value=300.0, sql=EVIL_SQL)
    record = TraceRecord(
        item_id=item.id,
        seed=1,
        repetition=0,
        condition="open",
        request=AgentRequest(
            item_id=item.id,
            question=item.question,
            schema_ddl="x",
            budget=Budget(max_calls=1, timeout_s=5),
        ),
        raw_payload={},
        response=response,
        execution=SqlExecution(status="ok", value=300.0, row_count=1),
    )
    verdict = Verdict(
        item_id=item.id,
        axes={
            "definitional": AxisResult(status="fail", evidence={"reason": "off by 3x"}),
            "grain": AxisResult(status="pass"),
            "ambiguity": AxisResult(status="na"),
            "refusal": AxisResult(status="pass"),
            "faithfulness": AxisResult(status="na"),
        },
        roll_up="fail",
    )
    manifest = RunManifest(
        tool_version="0.6.0",
        suite_version="t",
        suite_hash="h",
        world_hashes={"saas": "abc"},
        agent_id="naive",
        condition="open",
        seeds=(1,),
        repetitions=1,
        totals=RunTotals(items=1, cost_usd=0.0, latency_p50_ms=1.0, latency_p95_ms=2.0),
        git_commit="deadbeef",
        created_at=datetime.datetime(2026, 6, 12, tzinfo=datetime.UTC),
    )
    return item, record, verdict, manifest


def test_agent_sql_is_escaped_never_executed_as_markup(tmp_path) -> None:
    item, record, verdict, manifest = _fixture(tmp_path)
    render_report(
        [item],
        [record],
        [verdict],
        manifest,
        registries={},
        reference_dates={},
        weights={"definitional": 1.0},
        thresholds={"definitional": 0.8},
        judge_configured=False,
        out_path=tmp_path / "r.html",
    )
    html = (tmp_path / "r.html").read_text(encoding="utf-8")
    assert "<script>" not in html  # escaped, not raw
    assert "&lt;script&gt;" in html
    assert "&lt;b&gt;revenue&lt;/b&gt;" in html  # question escaped too


def test_gate_breach_is_reported(tmp_path) -> None:
    item, record, verdict, manifest = _fixture(tmp_path)
    result = render_report(
        [item],
        [record],
        [verdict],
        manifest,
        registries={},
        reference_dates={},
        weights={"definitional": 1.0},
        thresholds={"definitional": 0.8},
        judge_configured=False,
        out_path=tmp_path / "r.html",
    )
    assert result.breaches == ("definitional",)
    assert result.overall == 0.0
    assert result.extra["ran_fine"] == 1.0  # it executed fine -- and was wrong
    assert result.extra["business_correct"] == 0.0


def test_charts_escape_labels_and_bound_rates() -> None:
    svg = gap_chart(1.5, -0.2)  # out-of-range rates are clamped
    assert 'width="460.0"' in svg or 'width="460' in svg
    assert 'width="0.0"' in svg
    svg = axis_chart({"defi<nitional": 0.5})
    assert "defi&lt;nitional" in svg
