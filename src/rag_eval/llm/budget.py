"""A hard spending limit for one run.

The project's whole budget is ₹1000, and the realistic way to lose it is not
per-token price but a loop: a retry that never gives up, or a re-index that runs
once per case. This guard makes that impossible rather than unlikely.

When the limit is reached the run stops and says where. It does not skip the
remaining work quietly, because a report covering two-thirds of the cases while
claiming to cover all of them is worse than no report.
"""

from __future__ import annotations

from rag_eval.errors import RagEvalError


class BudgetExceededError(RagEvalError):
    """The run reached its spending limit and stopped."""

    def __init__(self, spent_usd: float, limit_usd: float, calls: int) -> None:
        """Record what had been spent, on what limit, after how many calls."""
        self.spent_usd = spent_usd
        self.limit_usd = limit_usd
        self.calls = calls
        super().__init__(
            f"Run stopped at its spending limit after {calls} model calls: "
            f"${spent_usd:.4f} spent against a ${limit_usd:.4f} limit. "
            "Results up to this point are complete; anything after it was not attempted."
        )


class BudgetGuard:
    """Tracks what a run has spent and refuses to let it exceed a limit."""

    def __init__(self, limit_usd: float) -> None:
        """Create a guard. A limit of zero or less is rejected as certainly a mistake."""
        if limit_usd <= 0:
            raise ValueError(f"budget limit must be positive, got {limit_usd}")
        self.limit_usd = limit_usd
        self.spent_usd = 0.0
        self.calls = 0

    @property
    def remaining_usd(self) -> float:
        """How much of the limit is left."""
        return max(0.0, self.limit_usd - self.spent_usd)

    def check(self, estimated_usd: float = 0.0) -> None:
        """Stop the run if it has already spent its limit, or would by making this call.

        Raises:
            BudgetExceededError: with what was spent and how far the run got.
        """
        if self.spent_usd + estimated_usd > self.limit_usd:
            raise BudgetExceededError(self.spent_usd, self.limit_usd, self.calls)

    def record(self, cost_usd: float) -> None:
        """Add the cost of a completed call. Cached calls cost nothing and still count."""
        self.spent_usd += cost_usd
        self.calls += 1
