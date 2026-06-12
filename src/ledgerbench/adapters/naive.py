"""Deterministic offline baseline adapter: no API key, no network, no model.

Templates SQL from question keywords and the schema DDL, runs it through the
gated callback, and always *answers*. That makes it the floor baseline by
design: it never clarifies, never refuses, and never reads the rulebook -- so
it walks into every trap the benchmark sets. CI and the demo use it because it
is fast, free, and bit-for-bit reproducible.

It is also the worked example for the adapter-in-100-lines promise in
CONTRIBUTING.md: real adapters do exactly this, with a model call in the middle.
"""

from __future__ import annotations

import re

from ledgerbench.adapters.base import AgentAdapter, ExecuteSql
from ledgerbench.contracts.agent_io import AgentRequest
from ledgerbench.errors import LedgerBenchError

_CREATE_TABLE = re.compile(r"CREATE\s+TABLE\s+(\w+)\s*\((.*?)\);", re.IGNORECASE | re.DOTALL)
_COLUMN = re.compile(r"^\s*(\w+)\s+(\w+)")
_NUMERIC_TYPES = ("DECIMAL", "DOUBLE", "FLOAT", "INTEGER", "BIGINT", "NUMERIC", "REAL")


def _split_top_level_commas(body: str) -> list[str]:
    """Split a CREATE TABLE body on commas outside parentheses (DECIMAL(10,2))."""
    chunks, depth, start = [], 0, 0
    for i, ch in enumerate(body):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            chunks.append(body[start:i].strip())
            start = i + 1
    chunks.append(body[start:].strip())
    return [c for c in chunks if c]


def _parse_schema(schema_ddl: str) -> dict[str, list[tuple[str, str]]]:
    """Extract {table: [(column, type), ...]} from CREATE TABLE DDL."""
    tables: dict[str, list[tuple[str, str]]] = {}
    for match in _CREATE_TABLE.finditer(schema_ddl):
        name, body = match.group(1).lower(), match.group(2)
        columns = []
        for chunk in _split_top_level_commas(body):
            col = _COLUMN.match(chunk)
            if col and col.group(1).upper() not in (
                "PRIMARY",
                "FOREIGN",
                "UNIQUE",
                "CHECK",
                "CONSTRAINT",
            ):
                columns.append((col.group(1).lower(), col.group(2).upper()))
        tables[name] = columns
    return tables


class NaiveAdapter(AgentAdapter):
    """Keyword-template baseline; always answers, never clarifies or refuses."""

    name = "naive"

    def complete(self, request: AgentRequest, execute_sql: ExecuteSql) -> object:
        """Build a templated query, execute it once, and answer with the result."""
        tables = _parse_schema(request.schema_ddl)
        if not tables:
            return {"action": "answer", "value": 0.0, "sql": "SELECT 0", "confidence": 0.1}

        question = request.question.lower()
        sql = self._template(question, tables)

        try:
            rows = execute_sql(sql)
            first = rows[0][0] if rows and rows[0] else None
            value = float(first) if isinstance(first, int | float) else 0.0
        except LedgerBenchError:
            # Even its own query being blocked does not stop the baseline from
            # confidently answering -- that is the failure mode being measured.
            value = 0.0
        return {
            "action": "answer",
            "value": value,
            "sql": sql,
            "assumptions": ["used the first plausible table and column from the schema"],
            "confidence": 0.3,
        }

    def _template(self, question: str, tables: dict[str, list[tuple[str, str]]]) -> str:
        """Deterministic keyword heuristics; first match wins, sorted order."""
        mentioned = [t for t in sorted(tables) if t.rstrip("s") in question or t in question]
        table = mentioned[0] if mentioned else self._fact_table(tables)
        columns = tables[table]

        if any(kw in question for kw in ("how many", "count", "number of")):
            return f"SELECT COUNT(*) FROM {table}"

        measure = self._measure_column(columns)
        if any(kw in question for kw in ("average", "avg", "mean")):
            return f"SELECT AVG({measure}) FROM {table}"
        return f"SELECT SUM({measure}) FROM {table}"

    @staticmethod
    def _fact_table(tables: dict[str, list[tuple[str, str]]]) -> str:
        """Prefer a table holding an 'amount'-like column; ties break by name."""
        for name in sorted(tables):
            if any(col in ("amount", "mrr", "debit") for col, _ in tables[name]):
                return name
        return sorted(tables)[0]

    @staticmethod
    def _measure_column(columns: list[tuple[str, str]]) -> str:
        for col, _ in columns:
            if col in ("amount", "mrr", "debit", "credit"):
                return col
        for col, type_ in columns:
            if any(t in type_ for t in _NUMERIC_TYPES) and not col.endswith("_id"):
                return col
        return "1"
