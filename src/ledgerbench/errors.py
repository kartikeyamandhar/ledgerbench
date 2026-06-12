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
