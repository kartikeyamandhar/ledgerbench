"""AgentAdapter ABC plus entry-point plugin discovery.

An adapter makes one agent speak the fixed JSON contract: it receives an
:class:`~ledgerbench.contracts.agent_io.AgentRequest` and returns a *raw*
payload (dict or JSON string). Parsing and validation happen centrally in the
executor -- one untrusted-input boundary, not one per adapter.

Adapters never receive a database handle. If the agent needs to run SQL while
reasoning, the executor passes a safety-gated, budget-counted callback; that is
the only road to the data (see SECURITY.md). Third parties ship adapters via
the ``ledgerbench.adapters`` entry-point group -- no fork required.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from importlib.metadata import entry_points

from ledgerbench.contracts.agent_io import AgentRequest
from ledgerbench.errors import AdapterError

ExecuteSql = Callable[[str], list[tuple[object, ...]]]
"""Safety-gated SQL execution offered to adapters; counted against the budget."""

ENTRY_POINT_GROUP = "ledgerbench.adapters"


class AgentAdapter(ABC):
    """Wraps one agent so the runner can drive it.

    Subclasses implement :meth:`complete`. Raise
    :class:`~ledgerbench.errors.AdapterError` only for transport/protocol
    failures (the executor retries those with backoff); a *bad answer* is
    returned as-is and scored, never raised.
    """

    #: Stable identifier used in configs, manifests, and the CLI.
    name: str = "base"

    @abstractmethod
    def complete(self, request: AgentRequest, execute_sql: ExecuteSql) -> object:
        """Answer one item; return the raw response payload (dict or JSON str).

        Args:
            request: The item question, schema DDL, optional context pack, and
                budget the adapter must respect.
            execute_sql: Safety-gated query callback (SELECT-only, read-only,
                capped); each call counts against ``request.budget.max_calls``.

        Returns:
            The raw payload to be parsed by ``parse_agent_response``. Anything
            malformed scores zero -- adapters should not pre-validate.
        """


def _builtin_adapters() -> dict[str, Callable[[], AgentAdapter]]:
    # Imported lazily so optional provider code never loads unless asked for.
    def naive() -> AgentAdapter:
        from ledgerbench.adapters.naive import NaiveAdapter

        return NaiveAdapter()

    def http_openai() -> AgentAdapter:
        from ledgerbench.adapters.http_openai import OpenAIAdapter

        return OpenAIAdapter()

    def anthropic() -> AgentAdapter:
        from ledgerbench.adapters.anthropic import AnthropicAdapter

        return AnthropicAdapter()

    return {"naive": naive, "http_openai": http_openai, "anthropic": anthropic}


def available_adapters() -> list[str]:
    """Names of built-in adapters plus any installed via entry points."""
    names = set(_builtin_adapters())
    names.update(ep.name for ep in entry_points(group=ENTRY_POINT_GROUP))
    return sorted(names)


def load_adapter(name: str) -> AgentAdapter:
    """Instantiate an adapter by name (built-ins first, then entry points).

    Raises:
        AdapterError: no adapter with that name is installed.
    """
    builtin = _builtin_adapters()
    if name in builtin:
        return builtin[name]()
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        if ep.name == name:
            adapter_cls = ep.load()
            adapter = adapter_cls()
            if not isinstance(adapter, AgentAdapter):
                raise AdapterError(f"entry point {name!r} is not an AgentAdapter")
            return adapter
    raise AdapterError(f"unknown adapter {name!r}; available: {', '.join(available_adapters())}")
