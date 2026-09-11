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
        unit_type: str = "requests",
    ) -> BudgetCheckResult:
        """Check whether a provider has budget for the requested units.

        Does NOT record usage. Call ``record_usage`` after the operation
        completes to account for the consumed units.

        Args:
            provider: Provider name (e.g. "flow", "gemini").
            units: Number of units to check.
            operation: What operation is being checked.
            model: Model name, if model-specific.
            unit_type: Unit dimension to check (e.g. "requests", "tokens").
                Default "requests" preserves backward compatibility.
        """
        budget = self._budgets.get(provider)

        if budget is None:
            return self._no_budget_result(provider, model, units, operation)

        local_budget = self._get_local_budget(budget, unit_type)
        if local_budget is None:
            return self._no_budget_result(
                provider, model, units, operation, budget=budget, unit_type=unit_type
            )

        self._ensure_thresholds(budget)
        self._maybe_reset(budget)

        current = self._get_usage(budget, unit_type)
        projected = current + units
        hard_stop = self._get_hard_stop(budget, unit_type)

        if hard_stop is not None and projected >= hard_stop:
            return self._build_result(
                budget,
                model,
                BudgetStatus.HARD_STOP,
                units,
                operation,
                projected,
                current,
                unit_type,
                message=(
                    f"Hard stop: {provider} budget exhausted "
                    f"({current}/{local_budget} used, "
                    f"requesting {units} -> projected {projected})."
                ),
                next_action="Wait for budget reset or increase local_budget.",
            )

        warning = self._get_warning(budget, unit_type)
        if warning is not None and projected >= warning:
            return self._build_result(
                budget,
                model,
                BudgetStatus.WARNING,
                units,
                operation,
                projected,
                current,
                unit_type,
                message=(
                    f"Warning: {provider} budget approaching limit "
                    f"({current}/{local_budget} used, "
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
            current,
            unit_type,
            message=f"{provider}: budget OK ({current}/{local_budget} used).",
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
        force: bool = False,
    ) -> ProviderUsage:
        """Record that a provider consumed ``units`` for an operation.

        Args:
            provider: Provider name.
            units: Number of units consumed.
            operation: What operation was performed.
            content_id: Optional content reference UUID.
            model: Model used, if applicable.
            unit_type: Unit dimension (e.g. "requests", "tokens").
            metadata: Additional metadata about the usage event.
            force: When ``True``, record usage even if the hard-stop threshold
                would be exceeded. Used for post-call recording when the resource
                has already been consumed and the actual usage must be accounted
                for (e.g. token counts from a completed API response).

        Raises:
            BudgetExceededError: If no budget is configured, or (when
            ``force=False``) the hard-stop threshold would be exceeded.
        """
        budget = self._budgets.get(provider)

        if budget is None:
            raise BudgetExceededError(self._no_budget_result(provider, model, units, operation))

        local_budget = self._get_local_budget(budget, unit_type)
        if local_budget is None:
            raise BudgetExceededError(
                self._no_budget_result(
                    provider, model, units, operation, budget=budget, unit_type=unit_type
                )
            )

        self._ensure_thresholds(budget)
        self._maybe_reset(budget)

        current = self._get_usage(budget, unit_type)
        projected = current + units
        hard_stop = self._get_hard_stop(budget, unit_type)
        if (
            not force
            and hard_stop is not None
            and projected >= hard_stop
        ):
            raise BudgetExceededError(
                self._build_result(
                    budget,
                    model,
                    BudgetStatus.HARD_STOP,
                    units,
                    operation,
                    projected,
                    current,
                    unit_type,
                    message=(
                        f"Hard stop: {provider} budget exhausted "
                        f"({current}/{local_budget} used, "
                        f"requesting {units} -> projected {projected})."
                    ),
                    next_action="Wait for budget reset or increase local_budget.",
                )
            )

        self._set_usage(budget, unit_type, projected)
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

    def _get_local_budget(self, budget: ProviderBudget, unit_type: str) -> int | None:
        """Get the local budget for a specific unit dimension.

        Per-dimension budgets (``local_budget_by_unit_type``) take precedence.
        Falls back to the primary ``local_budget`` for backward compatibility.
        """
        if unit_type in budget.local_budget_by_unit_type:
            return budget.local_budget_by_unit_type[unit_type]
        return budget.local_budget

    def _get_official_limit(self, budget: ProviderBudget, unit_type: str) -> int | None:
        """Get the official provider quota for a specific unit dimension."""
        if unit_type in budget.official_limit_by_unit_type:
            return budget.official_limit_by_unit_type[unit_type]
        return budget.official_limit

    def _get_hard_stop(self, budget: ProviderBudget, unit_type: str) -> int | None:
        """Get the hard-stop threshold for a specific unit dimension."""
        self._ensure_thresholds(budget)
        if unit_type in budget.hard_stop_threshold_by_unit_type:
            return budget.hard_stop_threshold_by_unit_type[unit_type]
        return budget.hard_stop_threshold

    def _get_warning(self, budget: ProviderBudget, unit_type: str) -> int | None:
        """Get the warning threshold for a specific unit dimension."""
        self._ensure_thresholds(budget)
        if unit_type in budget.warning_threshold_by_unit_type:
            return budget.warning_threshold_by_unit_type[unit_type]
        return budget.warning_threshold

    def _get_reserve(self, budget: ProviderBudget, unit_type: str) -> int | None:
        """Get the reserve for a specific unit dimension."""
        self._ensure_thresholds(budget)
        if unit_type in budget.reserve_by_unit_type:
            return budget.reserve_by_unit_type[unit_type]
        return budget.reserve

    def _get_usage(self, budget: ProviderBudget, unit_type: str) -> int:
        """Return current usage for the given unit dimension.

        For backward compatibility, ``unit_type="requests"`` returns
        ``budget.current_usage``. Other unit types use the per-type
        ``usage_by_unit_type`` dict.
        """
        if unit_type == "requests":
            return budget.current_usage
        return budget.usage_by_unit_type.get(unit_type, 0)

    def _set_usage(self, budget: ProviderBudget, unit_type: str, value: int) -> None:
        """Set current usage for the given unit dimension.

        For backward compatibility, ``unit_type="requests"`` sets
        ``budget.current_usage``. Other unit types are stored in the
        per-type ``usage_by_unit_type`` dict.
        """
        if unit_type == "requests":
            budget.current_usage = value
        else:
            budget.usage_by_unit_type[unit_type] = value

    def _ensure_thresholds(self, budget: ProviderBudget) -> None:
        """Calculate derived thresholds from local budgets if missing.

        Computes both primary (backward-compatible ``hard_stop_threshold`` /
        ``warning_threshold`` / ``reserve`` from the single ``local_budget``)
        and per-dimension thresholds from
        ``local_budget_by_unit_type``.
        """
        if budget.local_budget is not None and budget.hard_stop_threshold is None:
            thresholds = calculate_thresholds(budget.local_budget, self._policy)
            budget.warning_threshold = thresholds.warning
            budget.hard_stop_threshold = thresholds.hard_stop
            budget.reserve = thresholds.reserve

        for unit_type, local in budget.local_budget_by_unit_type.items():
            if unit_type not in budget.hard_stop_threshold_by_unit_type:
                thresholds = calculate_thresholds(local, self._policy)
                budget.hard_stop_threshold_by_unit_type[unit_type] = thresholds.hard_stop
                budget.warning_threshold_by_unit_type[unit_type] = thresholds.warning
                budget.reserve_by_unit_type[unit_type] = thresholds.reserve

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
            budget.usage_by_unit_type.clear()
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
        current_usage: int,
        unit_type: str,
        message: str,
        next_action: str,
    ) -> BudgetCheckResult:
        """Construct a ``BudgetCheckResult`` from the budget and check parameters."""
        official_limit = self._get_official_limit(budget, unit_type)
        local_budget = self._get_local_budget(budget, unit_type)
        warning = self._get_warning(budget, unit_type)
        hard_stop = self._get_hard_stop(budget, unit_type)
        reserve = self._get_reserve(budget, unit_type)

        return BudgetCheckResult(
            provider=budget.provider,
            model=model,
            status=status,
            current_usage=current_usage,
            projected_usage=projected,
            requested_units=units,
            operation=operation,
            local_budget=local_budget,
            official_limit=official_limit,
            warning_threshold=warning,
            hard_stop_threshold=hard_stop,
            reserve=reserve,
            is_official_limit=official_limit is not None,
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
        unit_type: str = "requests",
    ) -> BudgetCheckResult:
        """Build a ``NO_BUDGET`` result for missing or manual-only providers."""
        current = self._get_usage(budget, unit_type) if budget else 0
        local_budget = self._get_local_budget(budget, unit_type) if budget else None
        official_limit = self._get_official_limit(budget, unit_type) if budget else None

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
      per-dimension budgets are extracted into ``local_budget_by_unit_type``.
      Each dimension (``requests``, ``tokens``) is tracked independently.
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

        local_budget_by_unit_type: dict[str, int] = {}
        official_limit_by_unit_type: dict[str, int] = {}

        if isinstance(local_budget, dict):
            if local_budget.get("requests_per_day") is not None:
                local_budget_by_unit_type["requests"] = local_budget["requests_per_day"]
            if local_budget.get("tokens_per_day") is not None:
                local_budget_by_unit_type["tokens"] = local_budget["tokens_per_day"]
            local_budget = None

        if isinstance(official_limit, dict):
            if official_limit.get("requests_per_day") is not None:
                official_limit_by_unit_type["requests"] = official_limit["requests_per_day"]
            if official_limit.get("tokens_per_day") is not None:
                official_limit_by_unit_type["tokens"] = official_limit["tokens_per_day"]
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
            local_budget_by_unit_type=local_budget_by_unit_type,
            official_limit_by_unit_type=official_limit_by_unit_type,
            warning_threshold=warning_threshold,
            hard_stop_threshold=hard_stop_threshold,
            reserve=reserve,
            reset_strategy=raw.get("reset"),
            paid_fallback=provider_policy.paid_fallback,
        )

    return budgets
