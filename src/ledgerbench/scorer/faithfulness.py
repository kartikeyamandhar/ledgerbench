"""Axis 5 (explanation faithfulness): do stated assumptions match the executed SQL?

Everything that can be checked deterministically is: :func:`extract_sql_facts`
walks the SQL with sqlglot and surfaces tables, joins, filter predicates,
exclusions (negated predicates), date bounds, and aggregates -- no model
involved. The LLM judge is confined to the one step that is genuinely semantic:
"does this stated assumption match these extracted facts?" (RT-003).

Judge discipline: the prompt is versioned in this file; every assumption is
judged twice (callers run the judge at temperature 0); the two verdicts must
agree or the assumption is flagged ``unknown`` -- disagreement is surfaced,
never averaged. Calls are cached by content hash so reruns are free. The axis
never runs the judge when there are no assumptions to check.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import sqlglot
from pydantic import BaseModel, ConfigDict
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from ledgerbench.contracts.agent_io import AgentResponse
from ledgerbench.contracts.verdict import AxisResult

logger = logging.getLogger(__name__)

Judge = Callable[[str], str]
"""A judge takes the rendered prompt and returns its raw text reply."""

JUDGE_PROMPT_VERSION = "faithfulness-judge-v1"

AssumptionVerdict = Literal["supported", "contradicted", "unrelated", "unknown"]

_VERDICT_TOKEN = re.compile(r"\b(SUPPORTED|CONTRADICTED|UNRELATED)\b", re.IGNORECASE)


class SqlFacts(BaseModel):
    """Deterministically extracted, judge-readable facts about one query."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tables: tuple[str, ...]
    joins: tuple[str, ...]
    filters: tuple[str, ...]
    exclusions: tuple[str, ...]
    date_bounds: tuple[str, ...]
    aggregates: tuple[str, ...]

    def render(self) -> str:
        """One block of plain text the judge prompt embeds."""
        parts = [
            f"tables: {', '.join(self.tables) or '(none)'}",
            f"joins: {'; '.join(self.joins) or '(none)'}",
            f"filters: {'; '.join(self.filters) or '(none)'}",
            f"exclusions (negated predicates): {'; '.join(self.exclusions) or '(none)'}",
            f"date bounds: {'; '.join(self.date_bounds) or '(none)'}",
            f"aggregates: {', '.join(self.aggregates) or '(none)'}",
        ]
        return "\n".join(parts)


def _conjuncts(node: exp.Expression | None) -> list[exp.Expression]:
    if node is None:
        return []
    if isinstance(node, exp.And):
        return _conjuncts(node.this) + _conjuncts(node.expression)
    return [node]


_DATEISH = re.compile(r"(_ts\b|_date\b|_on\b|\bDATE\b|\bTIMESTAMP\b|\bINTERVAL\b)", re.IGNORECASE)


def extract_sql_facts(sql: str, *, dialect: str = "duckdb") -> SqlFacts | None:
    """Extract judge-readable facts from one SELECT; None if unparseable."""
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except (ParseError, TokenError, ValueError):
        return None
    if not isinstance(tree, exp.Select):
        return None

    tables = tuple(sorted({t.name for t in tree.find_all(exp.Table)}))
    joins = tuple(
        join.args["on"].sql(dialect=dialect)
        for join in tree.find_all(exp.Join)
        if join.args.get("on") is not None
    )

    filters: list[str] = []
    exclusions: list[str] = []
    date_bounds: list[str] = []
    for where in tree.find_all(exp.Where):
        for predicate in _conjuncts(where.this):
            rendered = predicate.sql(dialect=dialect)
            negated = isinstance(predicate, exp.Not | exp.NEQ) or rendered.upper().startswith(
                "NOT "
            )
            (exclusions if negated else filters).append(rendered)
            if _DATEISH.search(rendered):
                date_bounds.append(rendered)

    aggregates = tuple(
        dict.fromkeys(agg.sql(dialect=dialect) for agg in tree.find_all(exp.AggFunc))
    )
    return SqlFacts(
        tables=tables,
        joins=joins,
        filters=tuple(filters),
        exclusions=tuple(exclusions),
        date_bounds=tuple(date_bounds),
        aggregates=aggregates,
    )


def judge_prompt(assumption: str, facts: SqlFacts) -> str:
    """Render the versioned judge prompt for one assumption."""
    return (
        f"[{JUDGE_PROMPT_VERSION}]\n"
        "An analyst answered a question with a SQL query and stated an assumption.\n"
        "Decide whether the assumption MATCHES what the SQL actually does, based\n"
        "only on these mechanically extracted facts about the query:\n\n"
        f"{facts.render()}\n\n"
        f'Stated assumption: "{assumption}"\n\n'
        "Reply with exactly one word:\n"
        "SUPPORTED   - the SQL does what the assumption claims\n"
        "CONTRADICTED - the SQL does something that conflicts with the claim\n"
        "UNRELATED   - the claim is about context the SQL neither does nor conflicts with\n"
    )


def _parse_verdict(reply: str) -> AssumptionVerdict:
    match = _VERDICT_TOKEN.search(reply)
    if match is None:
        return "unknown"
    token = match.group(1).lower()
    return token  # type: ignore[return-value]  # regex guarantees the literal set


class CachingJudge:
    """Wrap any judge with a sha256 content-hash cache (memory + optional disk).

    Each distinct (prompt, run_index) pair is cached, so the double-run is two
    cached entries and a full re-score of an old run costs zero judge calls.
    """

    def __init__(self, judge: Judge, cache_dir: str | Path | None = None) -> None:
        self._judge = judge
        self._memory: dict[str, str] = {}
        self._dir = Path(cache_dir) if cache_dir is not None else None
        if self._dir is not None:
            self._dir.mkdir(parents=True, exist_ok=True)

    def __call__(self, prompt: str) -> str:
        """Return the cached reply for ``prompt``, calling the judge on a miss."""
        key = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        if key in self._memory:
            return self._memory[key]
        if self._dir is not None:
            path = self._dir / f"{key}.json"
            if path.is_file():
                reply = str(json.loads(path.read_text(encoding="utf-8"))["reply"])
                self._memory[key] = reply
                return reply
        reply = self._judge(prompt)
        self._memory[key] = reply
        if self._dir is not None:
            (self._dir / f"{key}.json").write_text(
                json.dumps({"version": JUDGE_PROMPT_VERSION, "reply": reply}),
                encoding="utf-8",
            )
        return reply


def judge_assumption(assumption: str, facts: SqlFacts, judge: Judge) -> AssumptionVerdict:
    """Judge one assumption twice; agreement required, else ``unknown``."""
    prompt = judge_prompt(assumption, facts)
    first = _parse_verdict(judge(prompt))
    second = _parse_verdict(judge(prompt + "\n"))  # distinct cache key, same question
    if first != second:
        logger.info("judge disagreement assumption=%r %s vs %s", assumption, first, second)
        return "unknown"
    return first


def score_faithfulness(response: AgentResponse, judge: Judge) -> AxisResult:
    """Score axis 5 for one response.

    No assumptions -> ``na`` (the judge never runs). Assumptions without
    parseable SQL -> ``fail`` (claims with nothing checkable behind them).
    Any contradicted assumption -> ``fail`` naming it; any judge disagreement
    -> ``unknown``; otherwise ``pass``.
    """
    if not response.assumptions:
        return AxisResult(status="na", evidence={"reason": "no stated assumptions"})

    facts = extract_sql_facts(response.sql) if response.sql else None
    if facts is None:
        return AxisResult(
            status="fail",
            evidence={"reason": "stated assumptions but no parseable SQL to check them against"},
        )

    verdicts: dict[str, str] = {}
    for assumption in response.assumptions:
        verdicts[assumption] = judge_assumption(assumption, facts, judge)

    evidence: dict[str, object] = {
        "verdicts": dict(verdicts),
        "facts": facts.render(),
        "judge_prompt_version": JUDGE_PROMPT_VERSION,
    }
    if any(v == "contradicted" for v in verdicts.values()):
        contradicted = [a for a, v in verdicts.items() if v == "contradicted"]
        evidence["contradicted"] = contradicted
        return AxisResult(status="fail", evidence=evidence)
    if any(v == "unknown" for v in verdicts.values()):
        return AxisResult(status="unknown", evidence=evidence)
    return AxisResult(status="pass", evidence=evidence)


class AnthropicJudge:
    """Live judge over httpx at temperature 0; used by the calibration script.

    Never used in CI -- tests inject scripted judges. Requires
    ``ANTHROPIC_API_KEY`` in the environment.
    """

    def __init__(self, model: str = "claude-haiku-4-5-20251001") -> None:
        self.model = model

    def __call__(self, prompt: str) -> str:
        """Send one judge prompt at temperature 0 and return the text reply."""
        import httpx

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set; the live judge needs it")
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            json={
                "model": self.model,
                "max_tokens": 10,
                "temperature": 0,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30.0,
        )
        response.raise_for_status()
        body = response.json()
        return "".join(b.get("text", "") for b in body["content"] if b.get("type") == "text")
