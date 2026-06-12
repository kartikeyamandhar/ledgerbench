"""Typed exception hierarchy for LedgerBench.

Every module raises from this hierarchy rather than bare exceptions, so callers
(and tests) can distinguish a malformed rulebook from a build failure without
string-matching messages.
"""

from __future__ import annotations


class LedgerBenchError(Exception):
    """Base class for every error raised by LedgerBench."""


class RulebookError(LedgerBenchError):
    """A rulebook file could not be read or parsed as YAML."""


class RulebookValidationError(RulebookError):
    """A rulebook parsed as YAML but failed schema or semantic validation.

    Raised, for example, when a relationship references an undeclared table or
    two metrics share an id. Subclasses :class:`RulebookError` so callers that
    only care that "the rulebook is bad" can catch the parent.
    """


class WorldBuildError(LedgerBenchError):
    """A world database could not be built from its schema and generator."""


class SQLSafetyError(LedgerBenchError):
    """Model-generated SQL was rejected by the safety gate.

    Raised *before* execution: the offending statement never reaches DuckDB.
    The message names the violated rule so traces and kill-tests can assert on
    the reason, not just the refusal.
    """


class BudgetExceededError(LedgerBenchError):
    """The run-level dollar cap was crossed; the executor aborts cleanly."""


class CallBudgetExceededError(BudgetExceededError):
    """One item used more gated SQL calls than its budget.

    Scoped to the item: the executor records the failure and moves on, unlike
    the run-level dollar cap, which aborts the whole run.
    """


class AdapterError(LedgerBenchError):
    """An adapter failed in transport or protocol (not in answer quality).

    Transport failures are retried with backoff; answer quality is never a
    reason to raise -- a bad answer is scored, not retried.
    """
