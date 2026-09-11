"""Unit tests for the budget/quota tracking system.

Covers ARCHITECTURE §20.1 unit test scope:
- Budget calculations
- Warning thresholds
- Hard-stop behavior
- Reset-period handling
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from content_engine.budgets.models import (
    BudgetCheckResult,
    BudgetPeriod,
    BudgetStatus,
    ProviderBudget,
    ProviderUsage,
)
from content_engine.budgets.policy import BudgetPolicy, BudgetThresholds, calculate_thresholds
from content_engine.budgets.tracker import (
    BudgetExceededError,
    BudgetTracker,
    load_budgets_from_config,
)


class MockClock:
    """Injectable clock for deterministic time-based tests."""

    def __init__(self, start: datetime):
        self.current = start

    def __call__(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current = self.current + delta


def t(hour: int = 0, day: int = 1) -> datetime:
    """Shortcut for creating a UTC datetime."""
    return datetime(2024, 1, day, hour, 0, 0, tzinfo=UTC)


# --- BudgetPolicy tests ---


class TestBudgetPolicy:
    def test_defaults_match_docs(self):
        policy = BudgetPolicy()
        assert policy.warning_percent == 80
        assert policy.hard_stop_percent == 100
        assert policy.reserve_percent == 20
        assert policy.paid_fallback is False

    def test_custom_policy(self):
        policy = BudgetPolicy(
            warning_percent=70,
            hard_stop_percent=90,
            reserve_percent=10,
            paid_fallback=False,
        )
        assert policy.warning_percent == 70
        assert policy.hard_stop_percent == 90
        assert policy.reserve_percent == 10

    def test_warning_percent_bounds(self):
        with pytest.raises(ValidationError):
            BudgetPolicy(warning_percent=101)
        with pytest.raises(ValidationError):
            BudgetPolicy(warning_percent=-1)

    def test_paid_fallback_defaults_false(self):
        """Paid fallback must never be enabled by default (PRD §9, §12)."""
        assert BudgetPolicy().paid_fallback is False


# --- calculate_thresholds tests ---


class TestCalculateThresholds:
    def test_flow_defaults(self):
        """Flow: 50 credits, 80% warning, 100% hard stop, 20% reserve."""
        policy = BudgetPolicy()
        thresholds = calculate_thresholds(50, policy)
        assert thresholds.warning == 40
        assert thresholds.hard_stop == 50
        assert thresholds.reserve == 10

    def test_custom_policy(self):
        policy = BudgetPolicy(warning_percent=70, hard_stop_percent=90, reserve_percent=10)
        thresholds = calculate_thresholds(100, policy)
        assert thresholds.warning == 70
        assert thresholds.hard_stop == 90
        assert thresholds.reserve == 10

    def test_zero_budget(self):
        thresholds = calculate_thresholds(0, BudgetPolicy())
        assert thresholds == BudgetThresholds(warning=0, hard_stop=0, reserve=0)

    def test_rounding_down(self):
        thresholds = calculate_thresholds(99, BudgetPolicy())
        assert thresholds.warning == 79  # int(99 * 80 / 100)
        assert thresholds.hard_stop == 99
        assert thresholds.reserve == 19  # int(99 * 20 / 100)


# --- ProviderBudget tests ---


class TestProviderBudget:
    def test_defaults(self):
        budget = ProviderBudget(
            provider="flow",
            period=BudgetPeriod.DAILY,
            local_budget=50,
        )
        assert budget.provider == "flow"
        assert budget.model is None
        assert budget.current_usage == 0
        assert budget.last_reset is None
        assert budget.paid_fallback is False

    def test_required_fields(self):
        with pytest.raises(ValidationError):
            ProviderBudget(period=BudgetPeriod.DAILY)
        with pytest.raises(ValidationError):
            ProviderBudget(provider="flow")
        budget = ProviderBudget(provider="flow", period=BudgetPeriod.DAILY, local_budget=None)
        assert budget.local_budget is None

    def test_negative_usage_rejected(self):
        with pytest.raises(ValidationError):
            ProviderBudget(
                provider="flow",
                period=BudgetPeriod.DAILY,
                local_budget=50,
                current_usage=-1,
            )

    def test_budget_period_values(self):
        assert BudgetPeriod.DAILY == "daily"
        assert BudgetPeriod.PROVIDER_DEFINED == "provider-defined"


# --- ProviderUsage tests ---


class TestProviderUsage:
    def test_create(self):
        usage = ProviderUsage(
            provider="flow",
            operation="generate",
            units=10,
            unit_type="credits",
            timestamp=t(),
        )
        assert usage.provider == "flow"
        assert usage.units == 10
        assert usage.model is None
        assert usage.content_id is None
        assert usage.metadata is None

    def test_required_fields(self):
        with pytest.raises(ValidationError):
            ProviderUsage(
                provider="flow",
                operation="generate",
                units=10,
                unit_type="credits",
                # timestamp missing
            )

    def test_negative_units_rejected(self):
        with pytest.raises(ValidationError):
            ProviderUsage(
                provider="flow",
                operation="generate",
                units=-1,
                unit_type="credits",
                timestamp=t(),
            )

    def test_with_all_fields(self):
        cid = uuid4()
        usage = ProviderUsage(
            provider="gemini",
            model="gemini-2.0-flash",
            operation="generate_script",
            content_id=cid,
            units=5,
            unit_type="requests",
            timestamp=t(),
            metadata={"video_topic": "RAG"},
        )
        assert usage.model == "gemini-2.0-flash"
        assert usage.content_id == cid
        assert usage.metadata == {"video_topic": "RAG"}


# --- BudgetTracker: check_allowance ---


class TestCheckAllowance:
    def _flow_budget(self) -> ProviderBudget:
        policy = BudgetPolicy()
        thresholds = calculate_thresholds(50, policy)
        return ProviderBudget(
            provider="flow",
            period=BudgetPeriod.DAILY,
            official_limit=50,
            local_budget=50,
            warning_threshold=thresholds.warning,
            hard_stop_threshold=thresholds.hard_stop,
            reserve=thresholds.reserve,
        )

    def test_ok_status(self):
        budget = self._flow_budget()
        tracker = BudgetTracker({"flow": budget})
        result = tracker.check_allowance("flow", units=5, operation="generate")
        assert result.status == BudgetStatus.OK

    def test_warning_status(self):
        budget = self._flow_budget()
        budget.current_usage = 38
        tracker = BudgetTracker({"flow": budget})
        result = tracker.check_allowance("flow", units=5, operation="generate")
        # 38 + 5 = 43 >= 40 (warning threshold)
        assert result.status == BudgetStatus.WARNING
        assert result.projected_usage == 43

    def test_hard_stop_status(self):
        budget = self._flow_budget()
        budget.current_usage = 48
        tracker = BudgetTracker({"flow": budget})
        result = tracker.check_allowance("flow", units=5, operation="generate")
        # 48 + 5 = 53 >= 50 (hard stop)
        assert result.status == BudgetStatus.HARD_STOP
        assert result.projected_usage == 53

    def test_hard_stop_exact_boundary(self):
        budget = self._flow_budget()
        budget.current_usage = 45
        tracker = BudgetTracker({"flow": budget})
        result = tracker.check_allowance("flow", units=5, operation="generate")
        # 45 + 5 = 50 >= 50 (hard stop)
        assert result.status == BudgetStatus.HARD_STOP

    def test_warning_exact_boundary(self):
        budget = self._flow_budget()
        budget.current_usage = 35
        tracker = BudgetTracker({"flow": budget})
        result = tracker.check_allowance("flow", units=5, operation="generate")
        # 35 + 5 = 40 >= 40 (warning)
        assert result.status == BudgetStatus.WARNING

    def test_no_budget_provider(self):
        tracker = BudgetTracker({})
        result = tracker.check_allowance("unknown", units=1, operation="test")
        assert result.status == BudgetStatus.NO_BUDGET
        assert result.local_budget is None

    def test_no_budget_manual_provider(self):
        budget = ProviderBudget(
            provider="notebooklm",
            period=BudgetPeriod.PROVIDER_DEFINED,
            official_limit=None,
            local_budget=None,
        )
        tracker = BudgetTracker({"notebooklm": budget})
        result = tracker.check_allowance("notebooklm", units=1, operation="research")
        assert result.status == BudgetStatus.NO_BUDGET
        assert result.local_budget is None
        assert result.is_official_limit is False

    def test_check_result_contains_error_info(self):
        """ARCHITECTURE §18: result must identify provider, usage, threshold, official-vs-local."""
        budget = self._flow_budget()
        budget.current_usage = 48
        tracker = BudgetTracker({"flow": budget})
        result = tracker.check_allowance("flow", units=5, operation="generate")
        assert result.provider == "flow"
        assert result.operation == "generate"
        assert result.current_usage == 48
        assert result.hard_stop_threshold == 50
        assert result.is_official_limit is True
        assert len(result.next_action) > 0
        assert len(result.message) > 0


# --- BudgetTracker: record_usage ---


class TestRecordUsage:
    def _flow_budget(self) -> ProviderBudget:
        policy = BudgetPolicy()
        thresholds = calculate_thresholds(50, policy)
        return ProviderBudget(
            provider="flow",
            period=BudgetPeriod.DAILY,
            official_limit=50,
            local_budget=50,
            warning_threshold=thresholds.warning,
            hard_stop_threshold=thresholds.hard_stop,
            reserve=thresholds.reserve,
        )

    def test_records_usage(self):
        budget = self._flow_budget()
        tracker = BudgetTracker({"flow": budget})
        usage = tracker.record_usage("flow", units=10, operation="generate")
        assert usage.units == 10
        assert budget.current_usage == 10
        assert len(tracker.usage_records()) == 1

    def test_multiple_records_accumulate(self):
        budget = self._flow_budget()
        tracker = BudgetTracker({"flow": budget})
        tracker.record_usage("flow", units=10, operation="generate")
        tracker.record_usage("flow", units=15, operation="generate")
        assert budget.current_usage == 25

    def test_record_exceeds_hard_stop_raises(self):
        budget = self._flow_budget()
        budget.current_usage = 48
        tracker = BudgetTracker({"flow": budget})
        with pytest.raises(BudgetExceededError) as exc_info:
            tracker.record_usage("flow", units=5, operation="generate")
        assert exc_info.value.result.status == BudgetStatus.HARD_STOP
        assert exc_info.value.result.projected_usage == 53
        assert budget.current_usage == 48  # unchanged

    def test_record_at_exact_hard_stop_raises(self):
        budget = self._flow_budget()
        budget.current_usage = 45
        tracker = BudgetTracker({"flow": budget})
        with pytest.raises(BudgetExceededError):
            tracker.record_usage("flow", units=5, operation="generate")
        assert budget.current_usage == 45

    def test_record_no_budget_raises(self):
        tracker = BudgetTracker({})
        with pytest.raises(BudgetExceededError) as exc_info:
            tracker.record_usage("unknown", units=1, operation="test")
        assert exc_info.value.result.status == BudgetStatus.NO_BUDGET

    def test_record_manual_provider_raises(self):
        budget = ProviderBudget(
            provider="notebooklm",
            period=BudgetPeriod.PROVIDER_DEFINED,
            local_budget=None,
        )
        tracker = BudgetTracker({"notebooklm": budget})
        with pytest.raises(BudgetExceededError) as exc_info:
            tracker.record_usage("notebooklm", units=1, operation="research")
        assert exc_info.value.result.status == BudgetStatus.NO_BUDGET

    def test_record_does_not_check_warning(self):
        """Warning threshold should not block recording; only hard stop blocks."""
        budget = self._flow_budget()
        budget.current_usage = 42  # past warning (40), not at hard stop (50)
        tracker = BudgetTracker({"flow": budget})
        usage = tracker.record_usage("flow", units=5, operation="generate")
        assert budget.current_usage == 47
        assert usage is not None

    def test_usage_record_fields(self):
        budget = self._flow_budget()
        clock = MockClock(t())
        tracker = BudgetTracker({"flow": budget}, clock=clock)
        cid = uuid4()
        usage = tracker.record_usage(
            "flow",
            units=10,
            operation="generate",
            content_id=cid,
            model="veo-lite",
            unit_type="credits",
            metadata={"cost": 10},
        )
        assert usage.content_id == cid
        assert usage.model == "veo-lite"
        assert usage.unit_type == "credits"
        assert usage.timestamp == t()
        assert usage.metadata == {"cost": 10}


# --- BudgetTracker: reset behavior ---


class TestResetBehavior:
    def _flow_budget_factory(self) -> ProviderBudget:
        policy = BudgetPolicy()
        thresholds = calculate_thresholds(50, policy)
        return ProviderBudget(
            provider="flow",
            period=BudgetPeriod.DAILY,
            official_limit=50,
            local_budget=50,
            warning_threshold=thresholds.warning,
            hard_stop_threshold=thresholds.hard_stop,
            reserve=thresholds.reserve,
        )

    def test_first_call_sets_last_reset(self):
        budget = self._flow_budget_factory()
        clock = MockClock(t())
        tracker = BudgetTracker({"flow": budget}, clock=clock)
        result = tracker.check_allowance("flow", units=1, operation="gen")
        assert result.status == BudgetStatus.OK
        assert budget.last_reset == t()

    def test_no_reset_within_24h(self):
        budget = self._flow_budget_factory()
        clock = MockClock(t(hour=12))
        tracker = BudgetTracker({"flow": budget}, clock=clock)
        tracker.record_usage("flow", units=40, operation="gen")
        assert budget.current_usage == 40

        clock.advance(timedelta(hours=2))  # 14 hours later
        result = tracker.check_allowance("flow", units=5, operation="gen")
        # 40 + 5 = 45, within hard stop of 50
        assert result.status == BudgetStatus.WARNING
        assert budget.current_usage == 40  # not reset

    def test_reset_after_24h(self):
        budget = self._flow_budget_factory()
        clock = MockClock(t(hour=12))
        tracker = BudgetTracker({"flow": budget}, clock=clock)
        tracker.record_usage("flow", units=40, operation="gen")
        assert budget.current_usage == 40

        # Advance past 24 hours
        clock.advance(timedelta(hours=25))
        result = tracker.check_allowance("flow", units=5, operation="gen")
        assert result.current_usage == 0  # reset
        assert result.status == BudgetStatus.OK

    def test_reset_restores_allowance(self):
        budget = self._flow_budget_factory()
        budget.current_usage = 50
        budget.last_reset = t(day=1)
        clock = MockClock(t(day=3))  # 2 days later
        tracker = BudgetTracker({"flow": budget}, clock=clock)
        result = tracker.check_allowance("flow", units=5, operation="gen")
        assert result.status == BudgetStatus.OK
        assert result.current_usage == 0

    def test_provider_defined_no_auto_reset(self):
        budget = ProviderBudget(
            provider="gemini",
            period=BudgetPeriod.PROVIDER_DEFINED,
            official_limit=None,
            local_budget=50,
            warning_threshold=40,
            hard_stop_threshold=50,
            reserve=10,
        )
        budget.current_usage = 50
        budget.last_reset = t(day=1)
        clock = MockClock(t(day=10))  # 9 days later
        tracker = BudgetTracker({"gemini": budget}, clock=clock)
        result = tracker.check_allowance("gemini", units=1, operation="gen")
        # Should NOT reset — provider-defined period
        assert result.status == BudgetStatus.HARD_STOP
        assert result.current_usage == 50

    def test_reset_updates_last_reset(self):
        budget = self._flow_budget_factory()
        budget.current_usage = 40
        budget.last_reset = t(day=1, hour=12)
        clock = MockClock(t(day=1, hour=12))
        tracker = BudgetTracker({"flow": budget}, clock=clock)

        clock.advance(timedelta(days=1))  # exactly 24h later
        tracker.check_allowance("flow", units=1, operation="gen")
        assert budget.last_reset == t(day=2, hour=12)
        assert budget.current_usage == 0


# --- load_budgets_from_config tests ---


class TestLoadBudgetsFromConfig:
    def test_flow_numeric_config(self):
        """PRD §8.1: Flow has 50 daily credits with explicit thresholds."""
        config = {
            "budgets": {
                "flow": {
                    "period": "daily",
                    "official_limit": 50,
                    "local_budget": 50,
                    "warning_percent": 80,
                    "hard_stop_percent": 100,
                    "reserve_percent": 20,
                    "reset": "first_generation_plus_24h",
                }
            }
        }
        budgets = load_budgets_from_config(config)
        flow = budgets["flow"]
        assert flow.provider == "flow"
        assert flow.period == BudgetPeriod.DAILY
        assert flow.official_limit == 50
        assert flow.local_budget == 50
        assert flow.warning_threshold == 40
        assert flow.hard_stop_threshold == 50
        assert flow.reserve == 10
        assert flow.reset_strategy == "first_generation_plus_24h"
        assert flow.paid_fallback is False

    def test_gemini_dict_config_becomes_none(self):
        """PRD §8.2: Gemini default config has null limits — treated as manual."""
        config = {
            "budgets": {
                "gemini": {
                    "model": "gemini-2.0-flash",
                    "period": "provider-defined",
                    "official_limit": {
                        "requests_per_minute": None,
                        "tokens_per_minute": None,
                        "requests_per_day": None,
                    },
                    "local_budget": {
                        "requests_per_day": None,
                        "tokens_per_day": None,
                    },
                    "warning_percent": 80,
                    "hard_stop_percent": 100,
                    "reserve_percent": 20,
                    "paid_fallback": False,
                }
            }
        }
        budgets = load_budgets_from_config(config)
        gemini = budgets["gemini"]
        assert gemini.model == "gemini-2.0-flash"
        assert gemini.period == BudgetPeriod.PROVIDER_DEFINED
        assert gemini.local_budget is None  # dict -> None (not automated)
        assert gemini.official_limit is None
        assert gemini.warning_threshold is None
        assert gemini.hard_stop_threshold is None

    def test_manual_provider_null_config(self):
        """NotebookLM (§8.3) and YouTube (§8.5): null budgets, manual only."""
        config = {
            "budgets": {
                "notebooklm": {
                    "period": "provider-defined",
                    "official_limit": None,
                    "local_budget": None,
                    "warning_percent": 80,
                    "hard_stop_percent": 100,
                    "paid_fallback": False,
                }
            }
        }
        budgets = load_budgets_from_config(config)
        nb = budgets["notebooklm"]
        assert nb.local_budget is None
        assert nb.official_limit is None
        assert nb.paid_fallback is False

    def test_per_provider_policy_override(self):
        config = {
            "budgets": {
                "flow": {
                    "period": "daily",
                    "local_budget": 100,
                    "warning_percent": 70,
                    "hard_stop_percent": 90,
                    "reserve_percent": 10,
                }
            }
        }
        budgets = load_budgets_from_config(config)
        flow = budgets["flow"]
        assert flow.warning_threshold == 70
        assert flow.hard_stop_threshold == 90
        assert flow.reserve == 10

    def test_empty_config(self):
        budgets = load_budgets_from_config({})
        assert budgets == {}

    def test_missing_budgets_key(self):
        budgets = load_budgets_from_config({"other_key": {}})
        assert budgets == {}

    def test_multiple_providers(self):
        config = {
            "budgets": {
                "flow": {"period": "daily", "local_budget": 50},
                "notebooklm": {"period": "provider-defined", "local_budget": None},
            }
        }
        budgets = load_budgets_from_config(config)
        assert "flow" in budgets
        assert "notebooklm" in budgets
        assert budgets["flow"].local_budget == 50
        assert budgets["notebooklm"].local_budget is None

    def test_paid_fallback_defaults_false(self):
        """Paid fallback must remain disabled (PRD §9, §12)."""
        config = {"budgets": {"flow": {"period": "daily", "local_budget": 50}}}
        budgets = load_budgets_from_config(config)
        assert budgets["flow"].paid_fallback is False

    def test_flow_tracker_operational(self):
        """End-to-end: load config, check allowance, record usage."""
        config = {
            "budgets": {
                "flow": {
                    "period": "daily",
                    "official_limit": 50,
                    "local_budget": 50,
                    "warning_percent": 80,
                    "hard_stop_percent": 100,
                    "reserve_percent": 20,
                }
            }
        }
        budgets = load_budgets_from_config(config)
        clock = MockClock(t())
        tracker = BudgetTracker(budgets, clock=clock)

        # Initially OK
        assert tracker.check_allowance("flow", units=10).status == BudgetStatus.OK

        # Record 40 units -> at warning boundary
        tracker.record_usage("flow", units=40, operation="generate")

        # Next check: 40 + 10 = 50 -> hard stop
        result = tracker.check_allowance("flow", units=10, operation="generate")
        assert result.status == BudgetStatus.HARD_STOP


# --- BudgetCheckResult tests ---


class TestBudgetCheckResult:
    def test_construction(self):
        budget = ProviderBudget(
            provider="flow",
            period=BudgetPeriod.DAILY,
            local_budget=50,
            warning_threshold=40,
            hard_stop_threshold=50,
            reserve=10,
        )
        result = BudgetCheckResult(
            provider="flow",
            model=None,
            status=BudgetStatus.WARNING,
            current_usage=40,
            projected_usage=45,
            requested_units=5,
            operation="generate",
            local_budget=50,
            official_limit=50,
            warning_threshold=40,
            hard_stop_threshold=50,
            reserve=10,
            is_official_limit=True,
            message="Warning: approaching limit",
            next_action="Monitor usage.",
        )
        assert result.provider == "flow"
        assert result.status == BudgetStatus.WARNING
        assert result.is_official_limit is True
        assert budget.warning_threshold == 40
