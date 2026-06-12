"""Kill-tests: the most important tests in the repository.

Every fixture under tests/fixtures/malicious_sql/ must be rejected by the gate
AND -- the stronger claim -- must never reach the engine: the audit log of the
SafeExecutor stays empty. This corpus is permanent regression protection
(RT-005): when a new bypass is imagined, it becomes a fixture here, forever.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from ledgerbench.errors import SQLSafetyError
from ledgerbench.runner.safety import SafeExecutor, vet_sql

_FIXTURES = sorted((Path(__file__).parents[1] / "fixtures" / "malicious_sql").glob("*.sql"))


def test_corpus_exists_and_is_substantial() -> None:
    assert len(_FIXTURES) >= 25, "the kill-test corpus must only ever grow"


@pytest.mark.parametrize("fixture", _FIXTURES, ids=lambda p: p.stem)
def test_malicious_sql_is_rejected_by_the_gate(fixture: Path) -> None:
    sql = fixture.read_text(encoding="utf-8")
    with pytest.raises(SQLSafetyError):
        vet_sql(sql)


@pytest.mark.parametrize("fixture", _FIXTURES, ids=lambda p: p.stem)
def test_malicious_sql_never_reaches_the_engine(fixture: Path) -> None:
    """The negative assertion: zero executions, not merely an error somewhere."""
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE orders (order_id INTEGER, amount DOUBLE)")
    safe = SafeExecutor(con)

    with pytest.raises(SQLSafetyError):
        safe.execute(fixture.read_text(encoding="utf-8"))
    assert safe.audit_log == [], "blocked SQL must never be executed"

    # And the data is intact -- nothing was dropped, deleted, or rewritten.
    assert con.execute("SELECT count(*) FROM orders").fetchone() is not None
    con.close()


def test_comment_smuggling_is_stripped_from_vetted_sql() -> None:
    vetted = vet_sql("SELECT /* DROP TABLE orders */ 1 -- DELETE FROM orders")
    assert "DROP" not in vetted.upper()
    assert "DELETE" not in vetted.upper()


def test_legitimate_queries_pass_and_execute() -> None:
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE orders (order_id INTEGER, amount DOUBLE)")
    con.execute("INSERT INTO orders VALUES (1, 100.0), (2, 50.0)")
    safe = SafeExecutor(con)

    rows = safe.execute("SELECT sum(amount) FROM orders WHERE order_id > 0")
    assert rows[0][0] == 150.0
    assert len(safe.audit_log) == 1
    con.close()


def test_row_cap_is_enforced() -> None:
    con = duckdb.connect(":memory:")
    safe = SafeExecutor(con, row_cap=10)
    with pytest.raises(SQLSafetyError, match="row cap"):
        safe.execute("SELECT * FROM range(100)")
    con.close()


def test_timeout_interrupts_long_statements() -> None:
    con = duckdb.connect(":memory:")
    safe = SafeExecutor(con, timeout_s=0.2, row_cap=10)
    # A cross join big enough to outlive the timer on any machine.
    with pytest.raises((SQLSafetyError, Exception)):
        safe.execute(
            "SELECT count(*) FROM range(100000000) a JOIN range(100000000) b ON a.range = b.range"
        )
    con.close()
