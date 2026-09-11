"""Data models for provider budget and quota tracking (ARCHITECTURE §5.2, §13)."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class BudgetPeriod(StrEnum):
    """Reset period for a provider budget."""

    DAILY = "daily"
    PROVIDER_DEFINED = "provider-defined"


class BudgetStatus(StrEnum):
    """Outcome of a budget allowance check."""

    OK = "ok"
    WARNING = "warning"
    HARD_STOP = "hard_stop"
    NO_BUDGET = "no_budget"


class ProviderBudget(BaseModel):
    """Runtime budget state for a single provider (ARCHITECTURE §5.2).

    Combines configuration-derived thresholds with runtime usage tracking.
    Fields match the conceptual model:
        provider, model, period, official_limit, local_budget,
        warning_threshold, hard_stop_threshold, reserve,
        current_usage, last_reset, reset_strategy.
    """

    provider: str = Field(description="Provider name (e.g. 'flow', 'gemini')")
    model: str | None = Field(
        default=None, description="Specific model name, if model-specific budget"
    )
    period: BudgetPeriod = Field(description="Reset period for usage tracking")
    official_limit: int | None = Field(
        default=None,
        description="Official provider quota, if known. None means unknown.",
    )
    local_budget: int | None = Field(
        default=None,
        description="Local safety budget. None = manual provider, no automated work.",
    )
    warning_threshold: int | None = Field(
        default=None,
        description="Usage level at which to warn (absolute units).",
    )
    hard_stop_threshold: int | None = Field(
        default=None,
        description="Usage level at which automated work is refused.",
    )
    reserve: int | None = Field(
        default=None,
        description="Protected reserve (absolute units, held back from consumption).",
    )
    current_usage: int = Field(default=0, ge=0, description="Units consumed in the current period")
    usage_by_unit_type: dict[str, int] = Field(
        default_factory=dict,
        description="Per-unit-type usage tracking (e.g. 'requests', 'tokens'). "
        "Empty dict for single-dimensional providers that use current_usage directly.",
    )
    local_budget_by_unit_type: dict[str, int] = Field(
        default_factory=dict,
        description="Per-dimension local budgets (e.g. {'requests': 10, 'tokens': 100000}). "
        "When populated, takes precedence over the single local_budget field per dimension.",
    )
    official_limit_by_unit_type: dict[str, int] = Field(
        default_factory=dict,
        description="Per-dimension official provider quotas.",
    )
    warning_threshold_by_unit_type: dict[str, int] = Field(
        default_factory=dict,
        description="Per-dimension warning thresholds (populated by BudgetTracker).",
    )
    hard_stop_threshold_by_unit_type: dict[str, int] = Field(
        default_factory=dict,
        description="Per-dimension hard-stop thresholds (populated by BudgetTracker).",
    )
    reserve_by_unit_type: dict[str, int] = Field(
        default_factory=dict,
        description="Per-dimension reserves (populated by BudgetTracker).",
    )
    last_reset: datetime | None = Field(
        default=None,
        description="When usage was last reset to zero.",
    )
    reset_strategy: str | None = Field(
        default=None,
        description="Reset strategy name (e.g. 'first_generation_plus_24h').",
    )
    paid_fallback: bool = Field(
        default=False,
        description="Whether to allow paid usage as a fallback. Must remain False per PRD §9.",
    )


class ProviderUsage(BaseModel):
    """Record of a single provider usage event (ARCHITECTURE §13 — ProviderUsage).

    Allows the application to explain how a local budget was consumed
    without claiming access to provider-side account balances.
    """

    provider: str = Field(description="Provider name")
    model: str | None = Field(default=None, description="Model used, if applicable")
    operation: str = Field(description="What operation was performed (e.g. 'generate')")
    content_id: UUID | None = Field(
        default=None,
        description="Reference to the content/workflow ID, if applicable.",
    )
    units: int = Field(ge=0, description="Number of units consumed")
    unit_type: str = Field(description="Unit type (e.g. 'requests', 'tokens', 'credits')")
    timestamp: datetime = Field(description="When the usage was recorded")
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Additional metadata about the usage event.",
    )


class BudgetCheckResult(BaseModel):
    """Result of checking whether a provider has budget for a requested operation.

    Designed to provide all information required by ARCHITECTURE §18 for
    error handling: provider, model/operation, current usage, configured
    threshold, whether the limit is official or local, and a recommended
    next action.
    """

    provider: str
    model: str | None
    status: BudgetStatus
    current_usage: int
    projected_usage: int
    requested_units: int
    operation: str | None
    local_budget: int | None
    official_limit: int | None
    warning_threshold: int | None
    hard_stop_threshold: int | None
    reserve: int | None
    is_official_limit: bool
    message: str
    next_action: str
