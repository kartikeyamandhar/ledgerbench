"""Adapter tests: naive determinism; provider adapters against mocked transports."""

from __future__ import annotations

import json

import httpx
import pytest

from ledgerbench.adapters.anthropic import AnthropicAdapter
from ledgerbench.adapters.base import available_adapters
from ledgerbench.adapters.http_openai import OpenAIAdapter
from ledgerbench.adapters.naive import NaiveAdapter
from ledgerbench.contracts.agent_io import AgentRequest, Budget, parse_agent_response
from ledgerbench.errors import AdapterError

SCHEMA = (
    "CREATE TABLE orders (order_id INTEGER PRIMARY KEY, amount DECIMAL(10,2) NOT NULL,"
    " status VARCHAR NOT NULL);\n"
    "CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, region VARCHAR);"
)


def _request(question: str) -> AgentRequest:
    return AgentRequest(
        item_id="t-1",
        question=question,
        schema_ddl=SCHEMA,
        budget=Budget(max_calls=3, timeout_s=5.0),
    )


def _fake_execute(sql: str) -> list[tuple[object, ...]]:
    return [(150.0,)]


# --- naive --------------------------------------------------------------------


def test_naive_is_deterministic_and_valid() -> None:
    adapter = NaiveAdapter()
    first = adapter.complete(_request("What was total revenue?"), _fake_execute)
    second = adapter.complete(_request("What was total revenue?"), _fake_execute)
    assert first == second
    parsed = parse_agent_response(first)
    assert parsed.__class__.__name__ == "AgentResponse"


def test_naive_templates_count_vs_sum() -> None:
    adapter = NaiveAdapter()
    count = adapter.complete(_request("How many orders are there?"), _fake_execute)
    total = adapter.complete(_request("What was total order amount?"), _fake_execute)
    assert isinstance(count, dict) and "COUNT(*)" in str(count["sql"])
    assert isinstance(total, dict) and "SUM(amount)" in str(total["sql"])


def test_naive_answers_even_when_its_query_is_blocked() -> None:
    def blocked(sql: str) -> list[tuple[object, ...]]:
        from ledgerbench.errors import SQLSafetyError

        raise SQLSafetyError("denied")

    payload = NaiveAdapter().complete(_request("Total revenue?"), blocked)
    assert isinstance(payload, dict) and payload["action"] == "answer"


def test_builtin_adapters_are_discoverable() -> None:
    names = available_adapters()
    assert {"naive", "http_openai", "anthropic"} <= set(names)


# --- provider adapters (mocked transports; never live) -------------------------


def _openai_body(text: str) -> dict:
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }


def _anthropic_body(text: str) -> dict:
    return {
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }


FINAL_JSON = json.dumps(
    {
        "action": "answer",
        "value": 150.0,
        "sql": "SELECT sum(amount) FROM orders",
        "assumptions": ["completed orders only"],
        "confidence": 0.8,
    }
)


def test_openai_probe_loop(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    replies = iter(
        [
            _openai_body(json.dumps({"sql_probe": "SELECT sum(amount) FROM orders"})),
            _openai_body(FINAL_JSON),
        ]
    )
    probes: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, json=next(replies))

    def execute(sql: str) -> list[tuple[object, ...]]:
        probes.append(sql)
        return [(150.0,)]

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OpenAIAdapter(model="gpt-4o-mini", client=client)
    raw = adapter.complete(_request("Total revenue?"), execute)

    assert probes == ["SELECT sum(amount) FROM orders"]
    parsed = parse_agent_response(raw)
    assert parsed.__class__.__name__ == "AgentResponse"
    assert adapter.last_cost_usd > 0  # usage accounted across both calls


def test_openai_missing_key_is_adapter_error(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(AdapterError, match="OPENAI_API_KEY"):
        OpenAIAdapter().complete(_request("q"), _fake_execute)


def test_openai_http_error_is_adapter_error(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream sad")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(AdapterError, match="transport"):
        OpenAIAdapter(client=client).complete(_request("q"), _fake_execute)


def test_anthropic_single_shot(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["temperature"] == 0
        assert request.headers["x-api-key"] == "test-key"
        return httpx.Response(200, json=_anthropic_body(FINAL_JSON))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = AnthropicAdapter(model="claude-haiku-4-5-20251001", client=client)
    raw = adapter.complete(_request("Total revenue?"), _fake_execute)

    parsed = parse_agent_response(raw)
    assert parsed.__class__.__name__ == "AgentResponse"
    assert adapter.last_cost_usd > 0


def test_anthropic_missing_key_is_adapter_error(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(AdapterError, match="ANTHROPIC_API_KEY"):
        AnthropicAdapter().complete(_request("q"), _fake_execute)


def test_probe_rejection_is_reported_to_the_model(monkeypatch) -> None:
    """A gate-blocked probe comes back as text, not an exception."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    seen_messages: list[list[dict]] = []
    replies = iter(
        [
            _openai_body(json.dumps({"sql_probe": "DROP TABLE orders"})),
            _openai_body(FINAL_JSON),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        seen_messages.append(json.loads(request.content)["messages"])
        return httpx.Response(200, json=next(replies))

    def execute(sql: str) -> list[tuple[object, ...]]:
        from ledgerbench.errors import SQLSafetyError

        raise SQLSafetyError("denied statement: DDL (DROP)")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    OpenAIAdapter(client=client).complete(_request("q"), execute)
    assert any("Query rejected" in m["content"] for m in seen_messages[-1])


def test_markdown_fences_are_stripped_as_transport_noise() -> None:
    from ledgerbench.adapters.http_openai import _strip_fences

    fenced = '```json\n{"action": "refuse", "refusal_reason": "no cost center"}\n```'
    assert _strip_fences(fenced) == '{"action": "refuse", "refusal_reason": "no cost center"}'
    assert _strip_fences('{"a": 1}') == '{"a": 1}'  # unfenced passes through
    assert _strip_fences("```\nplain\n```") == "plain"


def test_prose_wrapped_json_payload_is_extracted() -> None:
    from ledgerbench.adapters.http_openai import _extract_payload, _extract_probe

    prose = 'Let me think about this.\n\n{"sql_probe": "SELECT 1"}\nThanks!'
    assert _extract_probe(prose) == "SELECT 1"
    final = 'Here is my answer:\n```json\n{"action": "answer", "value": 5, "sql": "SELECT 5"}\n```'
    assert _extract_payload(final) == '{"action": "answer", "value": 5, "sql": "SELECT 5"}'
    assert _extract_payload("no json here at all") == "no json here at all"


def test_probe_engine_errors_are_feedback_not_crashes() -> None:
    """A hallucinated column raises a duckdb error; the model must see it as text."""
    from ledgerbench.adapters.http_openai import _run_probe

    def exploding(sql: str) -> list[tuple[object, ...]]:
        raise RuntimeError('Binder Error: Referenced column "currency" not found')

    reply = _run_probe("SELECT currency FROM orders", exploding)
    assert reply.startswith("Query failed:")
    assert "currency" in reply
