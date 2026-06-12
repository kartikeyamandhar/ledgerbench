"""Call and dollar caps with a clean hard abort.

The budget is a rail, not a hint: hitting the USD cap raises
:class:`~ledgerbench.errors.BudgetExceededError`, which the executor catches to
finalize a *valid partial manifest* -- traces already written stay usable, and
nothing is corrupted. Per-item SQL-call caps bound how much work a single item
can demand through the gated execution callback.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ledgerbench.errors import BudgetExceededError, CallBudgetExceededError

DEFAULT_MAX_CALLS_PER_ITEM = 3
DEFAULT_MAX_USD_PER_RUN = 5.0  # deliberately low; raise explicitly in config


@dataclass
class BudgetTracker:
    """Tracks per-item SQL calls and run-level spend against hard caps."""

    max_calls_per_item: int = DEFAULT_MAX_CALLS_PER_ITEM
    max_usd_per_run: float = DEFAULT_MAX_USD_PER_RUN
    spent_usd: float = 0.0
    _item_calls: dict[str, int] = field(default_factory=dict)

    def start_item(self, item_id: str) -> None:
        """Reset the call counter for a new item attempt."""
        self._item_calls[item_id] = 0

    def count_call(self, item_id: str) -> None:
        """Record one gated SQL execution for ``item_id``.

        Raises:
            BudgetExceededError: the item used more calls than its budget.
        """
        used = self._item_calls.get(item_id, 0) + 1
        self._item_calls[item_id] = used
        if used > self.max_calls_per_item:
            raise CallBudgetExceededError(
                f"item {item_id!r} exceeded max_calls_per_item={self.max_calls_per_item}"
            )

    def add_cost(self, usd: float) -> None:
        """Record model spend; abort the run when the cap is crossed.

        Raises:
            BudgetExceededError: the run-level USD cap was exceeded.
        """
        self.spent_usd += usd
        if self.spent_usd > self.max_usd_per_run:
            raise BudgetExceededError(
                f"run exceeded max_usd_per_run={self.max_usd_per_run:.2f} "
                f"(spent {self.spent_usd:.2f})"
            )

    def calls_used(self, item_id: str) -> int:
        """How many gated SQL calls ``item_id`` has used so far."""
        return self._item_calls.get(item_id, 0)
