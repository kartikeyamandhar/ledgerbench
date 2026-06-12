"""OpenAI-compatible chat adapter over plain httpx (no SDK in the runtime path).

Works against api.openai.com or any compatible endpoint (vLLM, llama.cpp
servers, gateways) via ``base_url``. The agent may probe the database before
answering: replying ``{"sql_probe": "SELECT ..."}`` runs the query through the
runner's safety-gated callback (counted against the item budget) and the rows
come back as the next user message. The final reply must be the contract JSON;
whatever comes back is returned raw -- parsing is the executor's job.

API keys come from the environment only and are sent in headers, never logged
and never written to traces.
"""

from __future__ import annotations

import json
import os

import httpx

from ledgerbench.adapters.base import AgentAdapter, ExecuteSql
from ledgerbench.contracts.agent_io import AgentRequest
from ledgerbench.errors import AdapterError, LedgerBenchError

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"

# Rough $/1M-token estimates for spend accounting; the budget cap is the rail.
_PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1": (2.00, 8.00),
}

SYSTEM_PROMPT = """\
You are a careful data analyst answering one question against a DuckDB schema.

You may first explore by replying ONLY {"sql_probe": "<one SELECT>"} -- the rows
come back as the next message. You have a limited number of probes.

Your FINAL reply must be ONLY a JSON object with these fields:
  action: "answer" | "clarify" | "refuse"
  value: number                (REQUIRED when action=answer: run your SQL via a
                                probe to compute the actual number first -- an
                                answer without a value scores zero)
  sql: string                  (the one SELECT that produces value)
  assumptions: array of short strings stating choices you made
  clarifying_question: string or null  (when the question is ambiguous, name the ambiguous term)
  refusal_reason: string or null       (when unanswerable, name the missing column/dimension)
  confidence: number in [0,1]

Clarify when the question is genuinely ambiguous. Refuse when the schema cannot
answer it, naming what is missing. No prose outside the JSON object, and do NOT
wrap the JSON in markdown code fences.
"""


class OpenAIAdapter(AgentAdapter):
    """Chat-completions adapter for OpenAI-compatible endpoints."""

    name = "http_openai"

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model or os.environ.get("LEDGERBENCH_OPENAI_MODEL", DEFAULT_MODEL)
        self.base_url = (
            base_url or os.environ.get("LEDGERBENCH_OPENAI_BASE_URL", DEFAULT_BASE_URL)
        ).rstrip("/")
        self._client = client
        self.last_cost_usd = 0.0

    def complete(self, request: AgentRequest, execute_sql: ExecuteSql) -> object:
        """Drive the probe loop and return the model's final raw payload."""
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise AdapterError("OPENAI_API_KEY is not set")

        self.last_cost_usd = 0.0
        context = f"\n\nBusiness rulebook:\n{request.context_pack}" if request.context_pack else ""
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Schema:\n{request.schema_ddl}{context}\n\n"
                f"Question: {request.question}",
            },
        ]
        client = self._client or httpx.Client(timeout=request.budget.timeout_s)

        try:
            for _ in range(request.budget.max_calls):
                text = self._chat(client, api_key, messages)
                probe = _extract_probe(text)
                if probe is None:
                    return _extract_payload(text)
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content": _run_probe(probe, execute_sql)})
            # Probes exhausted with no final answer yet: demand it in one last
            # turn (folded into the final probe-result message so roles still
            # alternate). SQL calls stay capped by the gated callback.
            messages[-1]["content"] += (
                "\n\nProbe budget exhausted -- no more queries are available. "
                "Reply now with ONLY the final JSON object (no sql_probe, no prose)."
            )
            text = self._chat(client, api_key, messages)
            return _extract_payload(text)
        finally:
            if self._client is None:
                client.close()

    def _chat(self, client: httpx.Client, api_key: str, messages: list[dict[str, str]]) -> str:
        try:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": self.model, "messages": messages, "temperature": 0},
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            raise AdapterError(f"openai transport failure: {exc}") from exc

        usage = body.get("usage", {})
        prices = _PRICES_PER_MTOK.get(self.model, (0.0, 0.0))
        self.last_cost_usd += (
            usage.get("prompt_tokens", 0) * prices[0]
            + usage.get("completion_tokens", 0) * prices[1]
        ) / 1_000_000

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AdapterError(f"openai response missing content: {exc}") from exc
        return str(content)


def _strip_fences(text: str) -> str:
    """Remove a markdown code fence wrapper, if present (transport noise).

    Models often wrap JSON in ```json fences despite instructions. Unwrapping
    is the adapter's job -- making the agent speak the contract -- and is not
    validation: whatever is inside still stands or falls on its own.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline != -1 and stripped.endswith("```"):
            return stripped[first_newline + 1 : -3].strip()
    return stripped


def _extract_payload(text: str) -> str:
    """Pull the contract JSON out of the model's transport text.

    Models wrap payloads in fences and prefix prose despite instructions.
    Unwrapping is the adapter's job (speak the contract); the extracted object
    still stands or falls on its own under ``parse_agent_response``. Strategy:
    fence-strip; if the result parses as JSON, done; otherwise scan for the
    first balanced ``{...}`` block that parses. If nothing parses, return the
    fence-stripped text -- which will be judged malformed, correctly.
    """
    stripped = _strip_fences(text)
    try:
        json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        pass
    else:
        return stripped

    start = stripped.find("{")
    while start != -1:
        depth = 0
        for index in range(start, len(stripped)):
            char = stripped[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidate = stripped[start : index + 1]
                    try:
                        json.loads(candidate)
                    except json.JSONDecodeError:
                        break
                    return candidate
        start = stripped.find("{", start + 1)
    return stripped


def _extract_probe(text: str) -> str | None:
    """Return the probe SQL when the reply's payload is a sql_probe object."""
    try:
        payload = json.loads(_extract_payload(text))
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(payload, dict) and set(payload) == {"sql_probe"}:
        probe = payload["sql_probe"]
        return probe if isinstance(probe, str) else None
    return None


def _run_probe(sql: str, execute_sql: ExecuteSql) -> str:
    """Run one probe through the gate; render rows (or the failure) as text.

    Any failure -- a safety rejection or an engine error from hallucinated
    columns/tables -- is feedback for the model, never an exception for the
    host: the agent gets to read its own mistake and try again.
    """
    try:
        rows = execute_sql(sql)
    except LedgerBenchError as exc:
        return f"Query rejected: {exc}"
    except Exception as exc:  # engine errors are agent feedback, never host crashes
        return f"Query failed: {str(exc)[:300]}"
    rendered = "\n".join(str(row) for row in rows[:50])
    suffix = f"\n... ({len(rows)} rows total)" if len(rows) > 50 else ""
    return f"Result rows:\n{rendered or '(no rows)'}{suffix}"
