"""Budget tracking — usage recording and threshold enforcement.

ARCHITECTURE §5 (Quota, Budget & Threshold Architecture),
§14 (CLI ``content budget status``),
§18 (Error Handling — quota/budget error requirements).
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from content_engine.budgets.models import (
    BudgetCheckResult,
    BudgetPeriod,
    BudgetStatus,
    ProviderBudget,
    ProviderUsage,
)
from content_engine.budgets.policy import BudgetPolicy, calculate_thresholds


class BudgetExceededError(Exception):
    """Raised when recording usage is not permitted.

    This includes two cases:
    1. No budget is configured for the provider (or local_budget is None).
    2. Recording usage would reach or exceed the hard-stop threshold.

    The exception carries the full ``BudgetCheckResult`` for structured
    error handling per ARCHITECTURE §18.
    """

    def __init__(self, result: BudgetCheckResult):
        self.result = result
        super().__init__(result.message)


class BudgetTracker:
    """Tracks provider usage and enforces budget thresholds.

    Usage pattern::

        tracker = BudgetTracker(budgets={"flow": flow_budget})
        result = tracker.check_allowance("flow", units=10, operation="generate")
        if result.status == BudgetStatus.OK:
            tracker.record_usage("flow", units=10, operation="generate")

    Args:
        budgets: Mapping of provider name to pre-configured ``ProviderBudget``.
        policy: Base ``BudgetPolicy`` for threshold calculation when a budget
            has ``local_budget`` set but missing derived thresholds.
        clock: Injectable time source for deterministic testing.
    """

    def __init__(
        self,
        budgets: dict[str, ProviderBudget],
        policy: BudgetPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self._budgets = budgets
        self._policy = policy or BudgetPolicy()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._usage_records: list[ProviderUsage] = []

    def get_budget(self, provider: str) -> ProviderBudget | None:
        """Return the budget for a provider, or ``None`` if not configured."""
        return self._budgets.get(provider)

    def check_allowance(
        self,
        provider: str,
        units: int = 1,
        operation: str | None = None,
        model: str | None = None,
    ) -> BudgetCheckResult:
        """Check whether a provider has budget for the requested units.

        Does NOT record usage. Call ``record_usage`` after the operation
        completes to account for the consumed units.
        """
        budget = self._budgets.get(provider)

        if budget is None:
            return self._no_budget_result(provider, model, units, operation)

        if budget.local_budget is None:
            return self._no_budget_result(provider, model, units, operation, budget=budget)

        self._ensure_thresholds(budget)
        self._maybe_reset(budget)

        projected = budget.current_usage + units

        if budget.hard_stop_threshold is not None and projected >= budget.hard_stop_threshold:
            return self._build_result(
                budget,
                model,
                BudgetStatus.HARD_STOP,
                units,
                operation,
                projected,
                message=(
                    f"Hard stop: {provider} budget exhausted "
                    f"({budget.current_usage}/{budget.local_budget} used, "
                    f"requesting {units} -> projected {projected})."
                ),
                next_action="Wait for budget reset or increase local_budget.",
            )

        if budget.warning_threshold is not None and projected >= budget.warning_threshold:
            return self._build_result(
                budget,
                model,
                BudgetStatus.WARNING,
                units,
                operation,
                projected,
                message=(
                    f"Warning: {provider} budget approaching limit "
                    f"({budget.current_usage}/{budget.local_budget} used, "
                    f"requesting {units} -> projected {projected})."
                ),
                next_action="Monitor usage; consider reducing consumption.",
            )

        return self._build_result(
            budget,
            model,
            BudgetStatus.OK,
            units,
            operation,
            projected,
            message=f"{provider}: budget OK ({budget.current_usage}/{budget.local_budget} used).",
            next_action="Proceed with operation.",
        )

    def record_usage(
        self,
        provider: str,
        units: int,
        operation: str,
        content_id: UUID | None = None,
        model: str | None = None,
        unit_type: str = "requests",
        metadata: dict[str, Any] | None = None,
    ) -> ProviderUsage:
        """Record that a provider consumed ``units`` for an operation.

        Raises:
            BudgetExceededError: If no budget is configured or the hard-stop
                threshold would be exceeded.
        """
        budget = self._budgets.get(provider)

        if budget is None:
            raise BudgetExceededError(self._no_budget_result(provider, model, units, operation))

        if budget.local_budget is None:
            raise BudgetExceededError(
                self._no_budget_result(provider, model, units, operation, budget=budget)
            )

        self._ensure_thresholds(budget)
        self._maybe_reset(budget)

        projected = budget.current_usage + units
        if budget.hard_stop_threshold is not None and projected >= budget.hard_stop_threshold:
            raise BudgetExceededError(
                self._build_result(
                    budget,
                    model,
                    BudgetStatus.HARD_STOP,
                    units,
                    operation,
                    projected,
                    message=(
                        f"Hard stop: {provider} budget exhausted "
                        f"({budget.current_usage}/{budget.local_budget} used, "
                        f"requesting {units} -> projected {projected})."
                    ),
                    next_action="Wait for budget reset or increase local_budget.",
                )
            )

        budget.current_usage = projected
        usage = ProviderUsage(
            provider=provider,
            model=model,
            operation=operation,
            content_id=content_id,
            units=units,
            unit_type=unit_type,
            timestamp=self._clock(),
            metadata=metadata,
        )
        self._usage_records.append(usage)
        return usage

    def usage_records(self) -> list[ProviderUsage]:
        """Return a copy of all recorded usage entries."""
        return list(self._usage_records)

    def _ensure_thresholds(self, budget: ProviderBudget) -> None:
        """Calculate derived thresholds from ``local_budget`` if missing."""
        if budget.local_budget is not None and budget.hard_stop_threshold is None:
            thresholds = calculate_thresholds(budget.local_budget, self._policy)
            budget.warning_threshold = thresholds.warning
            budget.hard_stop_threshold = thresholds.hard_stop
            budget.reserve = thresholds.reserve

    def _maybe_reset(self, budget: ProviderBudget) -> bool:
        """Reset ``current_usage`` if the budget period has elapsed.

        Returns ``True`` if a reset occurred. Only applies to ``DAILY``
        budgets. ``PROVIDER_DEFINED`` budgets are not auto-reset — their
        reset follows the provider's own schedule.
        """
        if budget.period != BudgetPeriod.DAILY:
            return False

        now = self._clock()
        if budget.last_reset is None:
            budget.last_reset = now
            return False

        if now - budget.last_reset >= timedelta(days=1):
            budget.current_usage = 0
            budget.last_reset = now
            return True

        return False

    def _build_result(
        self,
        budget: ProviderBudget,
        model: str | None,
        status: BudgetStatus,
        units: int,
        operation: str | None,
        projected: int,
        message: str,
        next_action: str,
    ) -> BudgetCheckResult:
        """Construct a ``BudgetCheckResult`` from the budget and check parameters."""
        return BudgetCheckResult(
            provider=budget.provider,
            model=model,
            status=status,
            current_usage=budget.current_usage,
            projected_usage=projected,
            requested_units=units,
            operation=operation,
            local_budget=budget.local_budget,
            official_limit=budget.official_limit,
            warning_threshold=budget.warning_threshold,
            hard_stop_threshold=budget.hard_stop_threshold,
            reserve=budget.reserve,
            is_official_limit=budget.official_limit is not None,
            message=message,
            next_action=next_action,
        )

    def _no_budget_result(
        self,
        provider: str,
        model: str | None,
        units: int,
        operation: str | None,
        budget: ProviderBudget | None = None,
    ) -> BudgetCheckResult:
        """Build a ``NO_BUDGET`` result for missing or manual-only providers."""
        local_budget = budget.local_budget if budget else None
        official_limit = budget.official_limit if budget else None
        current = budget.current_usage if budget else 0
        return BudgetCheckResult(
            provider=provider,
            model=model,
            status=BudgetStatus.NO_BUDGET,
            current_usage=current,
            projected_usage=current + units,
            requested_units=units,
            operation=operation,
            local_budget=local_budget,
            official_limit=official_limit,
            warning_threshold=None,
            hard_stop_threshold=None,
            reserve=None,
            is_official_limit=official_limit is not None,
            message=(
                f"No automated budget configured for provider '{provider}'. "
                f"Automated work is not permitted until a local_budget is set."
            ),
            next_action="Configure a local_budget in the budget configuration.",
        )


def load_budgets_from_config(
    config: dict[str, Any],
    policy: BudgetPolicy | None = None,
) -> dict[str, ProviderBudget]:
    """Load provider budgets from a parsed configuration dict (ARCHITECTURE §5.4).

    Handles three config shapes:
    - **Numeric budgets** (e.g. Flow): ``official_limit`` and ``local_budget``
      are integers; thresholds are calculated from the policy percentages.
    - **Dict budgets** (e.g. Gemini with ``requests_per_day``/``tokens_per_day``):
      treated as ``None`` — multi-dimensional budget tracking is not yet
      supported. A local budget must be configured explicitly before
      automated work is allowed (PRD §8.2).
    - **Null budgets** (e.g. NotebookLM, YouTube): both ``official_limit``
      and ``local_budget`` are ``None`` — manual providers only.

    Args:
        config: Parsed YAML config with a top-level ``budgets`` key.
        policy: Optional base policy; defaults to ``BudgetPolicy()``.
    """
    base_policy = policy or BudgetPolicy()
    budgets: dict[str, ProviderBudget] = {}
    raw_budgets = config.get("budgets", {})

    for name, raw in raw_budgets.items():
        provider_policy = BudgetPolicy(
            warning_percent=raw.get("warning_percent", base_policy.warning_percent),
            hard_stop_percent=raw.get("hard_stop_percent", base_policy.hard_stop_percent),
            reserve_percent=raw.get("reserve_percent", base_policy.reserve_percent),
            paid_fallback=raw.get("paid_fallback", base_policy.paid_fallback),
        )

        period_str = raw.get("period", "provider-defined")
        local_budget = raw.get("local_budget")
        official_limit = raw.get("official_limit")

        # Dict-style budgets (e.g. Gemini with requests_per_day/tokens_per_day)
        # are not yet supported for automated tracking. Per PRD §8.2 the
        # default config has all values null; a local budget must be
        # explicitly configured before automated work is allowed.
        if isinstance(local_budget, dict):
            local_budget = None
        if isinstance(official_limit, dict):
            official_limit = None

        if isinstance(local_budget, int):
            thresholds = calculate_thresholds(local_budget, provider_policy)
            warning_threshold = thresholds.warning
            hard_stop_threshold = thresholds.hard_stop
            reserve = thresholds.reserve
        else:
            warning_threshold = None
            hard_stop_threshold = None
            reserve = None

        budgets[name] = ProviderBudget(
            provider=name,
            model=raw.get("model"),
            period=BudgetPeriod(period_str),
            official_limit=official_limit,
            local_budget=local_budget,
            warning_threshold=warning_threshold,
            hard_stop_threshold=hard_stop_threshold,
            reserve=reserve,
            reset_strategy=raw.get("reset"),
            paid_fallback=provider_policy.paid_fallback,
        )

    return budgets
