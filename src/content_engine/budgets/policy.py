"""Budget policy — default safety thresholds (ARCHITECTURE §5.3, PRD §9).

These percentages are our local safety policy, not provider guarantees.
Defaults: Warning 80%, Hard stop 100%, Reserve 20%, Paid fallback disabled.
"""

from typing import NamedTuple

from pydantic import BaseModel, Field


class BudgetThresholds(NamedTuple):
    """Absolute thresholds calculated from a local budget and a policy."""

    warning: int
    hard_stop: int
    reserve: int


class BudgetPolicy(BaseModel):
    """Default safety policy for provider budgets.

    Every percentage is local policy, not a provider guarantee.
    The config can override these per-provider via ``warning_percent``,
    ``hard_stop_percent``, ``reserve_percent`` in the budget YAML
    (ARCHITECTURE §5.4) without changing application code (PRD §9,
    requirement 7).
    """

    warning_percent: int = Field(default=80, ge=0, le=100)
    hard_stop_percent: int = Field(default=100, ge=0, le=100)
    reserve_percent: int = Field(default=20, ge=0, le=100)
    paid_fallback: bool = Field(default=False)


def calculate_thresholds(local_budget: int, policy: BudgetPolicy) -> BudgetThresholds:
    """Calculate absolute warning, hard-stop, and reserve values from a local budget.

    Args:
        local_budget: The local safety budget (absolute units).
        policy: The policy with threshold percentages.

    Returns:
        BudgetThresholds with absolute values derived from the policy.
    """
    warning = int(local_budget * policy.warning_percent / 100)
    hard_stop = int(local_budget * policy.hard_stop_percent / 100)
    reserve = int(local_budget * policy.reserve_percent / 100)
    return BudgetThresholds(warning=warning, hard_stop=hard_stop, reserve=reserve)
