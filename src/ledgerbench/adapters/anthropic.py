"""Anthropic Messages API adapter over plain httpx (no SDK in the runtime path).

Same probe-loop protocol as the OpenAI adapter: the model may reply
``{"sql_probe": "SELECT ..."}`` to run one gated query (counted against the
item budget) before giving its final contract JSON. Keys come from the
environment only; never logged, never traced.
"""

from __future__ import annotations

import os

import httpx

from ledgerbench.adapters.base import AgentAdapter, ExecuteSql
from ledgerbench.adapters.http_openai import SYSTEM_PROMPT, _extract_probe, _run_probe
from ledgerbench.contracts.agent_io import AgentRequest
from ledgerbench.errors import AdapterError

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

# Rough $/1M-token estimates for spend accounting; the budget cap is the rail.
_PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-8": (5.00, 25.00),
}


class AnthropicAdapter(AgentAdapter):
    """Messages-API adapter for Claude models."""

    name = "anthropic"

    def __init__(self, model: str | None = None, client: httpx.Client | None = None) -> None:
        self.model = model or os.environ.get("LEDGERBENCH_ANTHROPIC_MODEL", DEFAULT_MODEL)
        self._client = client
        self.last_cost_usd = 0.0

    def complete(self, request: AgentRequest, execute_sql: ExecuteSql) -> object:
        """Drive the probe loop and return the model's final raw payload."""
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise AdapterError("ANTHROPIC_API_KEY is not set")

        self.last_cost_usd = 0.0
        context = f"\n\nBusiness rulebook:\n{request.context_pack}" if request.context_pack else ""
        messages: list[dict[str, str]] = [
            {
                "role": "user",
                "content": f"Schema:\n{request.schema_ddl}{context}\n\n"
                f"Question: {request.question}",
            }
        ]
        client = self._client or httpx.Client(timeout=request.budget.timeout_s)

        try:
            for _ in range(request.budget.max_calls):
                text = self._message(client, api_key, messages)
                probe = _extract_probe(text)
                if probe is None:
                    return text
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content": _run_probe(probe, execute_sql)})
            return text
        finally:
            if self._client is None:
                client.close()

    def _message(self, client: httpx.Client, api_key: str, messages: list[dict[str, str]]) -> str:
        try:
            response = client.post(
                API_URL,
                headers={"x-api-key": api_key, "anthropic-version": API_VERSION},
                json={
                    "model": self.model,
                    "max_tokens": 1024,
                    "temperature": 0,
                    "system": SYSTEM_PROMPT,
                    "messages": messages,
                },
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            raise AdapterError(f"anthropic transport failure: {exc}") from exc

        usage = body.get("usage", {})
        prices = _PRICES_PER_MTOK.get(self.model, (0.0, 0.0))
        self.last_cost_usd += (
            usage.get("input_tokens", 0) * prices[0] + usage.get("output_tokens", 0) * prices[1]
        ) / 1_000_000

        try:
            blocks = body["content"]
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except (KeyError, TypeError) as exc:
            raise AdapterError(f"anthropic response missing content: {exc}") from exc
        if not text:
            raise AdapterError("anthropic response contained no text blocks")
        return text
