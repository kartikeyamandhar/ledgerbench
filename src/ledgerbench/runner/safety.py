"""The SELECT-only gate, statement timeout, and row cap. The security boundary.

Every model-generated statement passes :func:`vet_sql` before execution: sqlglot
parse (duckdb dialect), exactly one statement, the root must be a SELECT, and a
structural denylist rejects DDL/DML, COPY/EXPORT, ATTACH/DETACH, INSTALL/LOAD,
PRAGMA, SET/RESET, CALL, transactions, and any function touching the filesystem
or network (``read_csv``, ``read_parquet``, ``read_json``, ``glob``, ``http*``,
and friends). Unparseable SQL is rejected, never executed.

Defense in depth: the gate is layer one. :class:`SafeExecutor` adds layer two
(connections opened read-only by the caller; a statement timeout enforced by an
interrupt timer; a row cap on results) and an audit log of every statement that
actually reached DuckDB -- so kill-tests can assert the negative: blocked SQL
was *never executed*, not merely errored somewhere.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from ledgerbench.errors import SQLSafetyError

if TYPE_CHECKING:
    import duckdb

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 30.0
DEFAULT_ROW_CAP = 100_000

# Statement-level nodes that must never execute. sqlglot parses many dialect
# statements into these; anything not parsed as a plain SELECT is refused by
# the root-type check anyway -- this list exists to give precise reasons.
_DENIED_STATEMENTS: tuple[tuple[type[exp.Expression], str], ...] = (
    (exp.Create, "DDL (CREATE)"),
    (exp.Drop, "DDL (DROP)"),
    (exp.Alter, "DDL (ALTER)"),
    (exp.Insert, "DML (INSERT)"),
    (exp.Update, "DML (UPDATE)"),
    (exp.Delete, "DML (DELETE)"),
    (exp.Merge, "DML (MERGE)"),
    (exp.TruncateTable, "DML (TRUNCATE)"),
    (exp.Copy, "COPY"),
    (exp.Export, "EXPORT"),
    (exp.Attach, "ATTACH"),
    (exp.Detach, "DETACH"),
    (exp.Install, "INSTALL"),
    (exp.Pragma, "PRAGMA"),
    (exp.Set, "SET"),
    (exp.Command, "raw command passthrough"),
    (exp.Transaction, "transaction control"),
    (exp.Commit, "transaction control"),
    (exp.Rollback, "transaction control"),
    (exp.Use, "USE"),
    (exp.Grant, "GRANT"),
)

# Function names (lowercase) that touch the filesystem, network, or host
# environment. Matched against exact names and as prefixes where noted.
_DENIED_FUNCTIONS: frozenset[str] = frozenset(
    {
        "read_csv",
        "read_csv_auto",
        "read_parquet",
        "parquet_scan",
        "read_json",
        "read_json_auto",
        "read_json_objects",
        "read_ndjson",
        "read_ndjson_auto",
        "read_text",
        "read_blob",
        "read_xlsx",
        "glob",
        "getenv",
        "load_extension",
        "install_extension",
        "sniff_csv",
        "copy",
        "duckdb_secrets",
    }
)
_DENIED_FUNCTION_PREFIXES: tuple[str, ...] = ("http", "st_read", "iceberg_", "delta_", "azure_")


def _function_name(node: exp.Func) -> str | None:
    """Best-effort lowercase name for any function-like AST node."""
    if isinstance(node, exp.Anonymous):
        this = node.this
        return this.lower() if isinstance(this, str) else None
    name = type(node).sql_name()
    return name.lower() if isinstance(name, str) else None


def vet_sql(sql: str, *, dialect: str = "duckdb") -> str:
    """Vet one model-generated statement; return it normalized or raise.

    Args:
        sql: Untrusted SQL from an agent.
        dialect: sqlglot dialect to parse with.

    Returns:
        The single vetted SELECT, rendered back to SQL (comments stripped --
        comment smuggling dies here).

    Raises:
        SQLSafetyError: naming the violated rule. The statement was not, and
            will not be, executed.
    """
    if not sql or not sql.strip():
        raise SQLSafetyError("empty statement")

    try:
        statements = sqlglot.parse(sql, read=dialect)
    except (ParseError, TokenError, ValueError) as exc:
        raise SQLSafetyError(f"unparseable SQL is never executed: {exc}") from exc

    parsed = [s for s in statements if s is not None]
    if len(parsed) != 1:
        raise SQLSafetyError(f"exactly one statement required, got {len(parsed)}")
    tree = parsed[0]

    for node_type, reason in _DENIED_STATEMENTS:
        if isinstance(tree, node_type) or tree.find(node_type) is not None:
            raise SQLSafetyError(f"denied statement: {reason}")

    if not isinstance(tree, exp.Select | exp.Union | exp.Intersect | exp.Except):
        raise SQLSafetyError(f"only SELECT is allowed, got {type(tree).__name__}")
    if isinstance(tree, exp.Select) and tree.args.get("into") is not None:
        raise SQLSafetyError("denied statement: SELECT INTO")

    for func in tree.find_all(exp.Func):  # exp.Anonymous subclasses Func
        name = _function_name(func)
        if name is None:
            continue
        if name in _DENIED_FUNCTIONS or name.startswith(_DENIED_FUNCTION_PREFIXES):
            raise SQLSafetyError(f"denied function: {name}")

    # Re-render: normalizes whitespace and drops comments, so nothing an agent
    # smuggled into a comment survives to the engine.
    return tree.sql(dialect=dialect, comments=False)


@dataclass
class SafeExecutor:
    """Execute vetted SELECTs on a DuckDB connection with hard rails.

    The caller is responsible for opening the connection read-only (the demo
    and runner always do); this class adds vetting, a statement timeout via
    ``connection.interrupt()`` from a timer thread, a row cap on fetches, and
    an audit log of every statement that actually reached the engine.
    """

    connection: duckdb.DuckDBPyConnection
    timeout_s: float = DEFAULT_TIMEOUT_S
    row_cap: int = DEFAULT_ROW_CAP
    audit_log: list[str] = field(default_factory=list)

    def execute(self, sql: str, *, dialect: str = "duckdb") -> list[tuple[object, ...]]:
        """Vet and execute one statement; return at most ``row_cap`` rows.

        Raises:
            SQLSafetyError: the statement failed the gate (never executed) or
                exceeded the row cap / timeout (executed but refused).
        """
        vetted = vet_sql(sql, dialect=dialect)

        timer = threading.Timer(self.timeout_s, self.connection.interrupt)
        timer.start()
        self.audit_log.append(vetted)
        try:
            cursor = self.connection.execute(vetted)
            rows: list[tuple[object, ...]] = cursor.fetchmany(self.row_cap + 1)
        except Exception as exc:  # duckdb raises its own hierarchy; classify
            if "INTERRUPT" in str(exc).upper():
                raise SQLSafetyError(f"statement timeout after {self.timeout_s}s") from exc
            raise
        finally:
            timer.cancel()

        if len(rows) > self.row_cap:
            raise SQLSafetyError(f"result exceeds the row cap ({self.row_cap})")
        logger.info("safe_execute rows=%d sql_len=%d", len(rows), len(vetted))
        return rows
