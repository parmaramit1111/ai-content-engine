"""Unit tests for the Gemini provider with budget enforcement.

All tests use mocks for the google.genai SDK — no network calls are made.
Covers ARCHITECTURE §4.2 (provider abstraction) and §7 (Gemini integration).
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from content_engine.budgets.models import BudgetPeriod, BudgetStatus, ProviderBudget
from content_engine.budgets.policy import BudgetPolicy, calculate_thresholds
from content_engine.budgets.tracker import BudgetTracker, load_budgets_from_config
from content_engine.providers.base import TextGenerationProvider
from content_engine.providers.exceptions import (
    ProviderAPIError,
    ProviderConfigurationError,
    ProviderQuotaError,
)
from content_engine.providers.gemini.provider import PROVIDER_NAME, GeminiProvider
from content_engine.providers.results import GenerationResult, GenerationUsage

TOKEN_BUDGET = 100


def _make_tracker_with_budget(local_budget: int = 100) -> BudgetTracker:
    thresholds = calculate_thresholds(local_budget, BudgetPolicy())
    budget = ProviderBudget(
        provider=PROVIDER_NAME,
        period=BudgetPeriod.DAILY,
        official_limit=None,
        local_budget=local_budget,
        warning_threshold=thresholds.warning,
        hard_stop_threshold=thresholds.hard_stop,
        reserve=thresholds.reserve,
    )
    return BudgetTracker({PROVIDER_NAME: budget})


def _make_no_budget_tracker() -> BudgetTracker:
    budget = ProviderBudget(
        provider=PROVIDER_NAME,
        period=BudgetPeriod.PROVIDER_DEFINED,
        official_limit=None,
        local_budget=None,
    )
    return BudgetTracker({PROVIDER_NAME: budget})


def _make_hard_stop_tracker() -> BudgetTracker:
    budget = ProviderBudget(
        provider=PROVIDER_NAME,
        period=BudgetPeriod.DAILY,
        official_limit=None,
        local_budget=100,
        warning_threshold=80,
        hard_stop_threshold=100,
        reserve=20,
    )
    budget.current_usage = 100
    return BudgetTracker({PROVIDER_NAME: budget})


class MockUsageMetadata:
    def __init__(self, prompt: int, candidates: int, total: int | None = None):
        self.prompt_token_count = prompt
        self.candidates_token_count = candidates
        self.total_token_count = total if total is not None else prompt + candidates


class MockGenerationResponse:
    def __init__(self, text: str, usage: MockUsageMetadata | None = None):
        self.text = text
        self.usage_metadata = usage
        self.model_version = "gemini-2.0-flash"


def _make_mock_client(response: MockGenerationResponse) -> MagicMock:
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=response)
    return mock_client


def _make_api_error(code: int, message: str) -> Exception:
    from google.genai import errors as genai_errors

    return genai_errors.APIError(
        code=code,
        response_json={"error": {"message": message}},
        response=None,
    )


# --- Init / configuration tests ---


class TestGeminiProviderInit:
    def test_missing_api_key_raises(self):
        tracker = _make_tracker_with_budget()
        with pytest.raises(ProviderConfigurationError, match="Missing GEMINI_API_KEY"):
            GeminiProvider(api_key=None, model="gemini-2.0-flash", tracker=tracker)

    def test_empty_api_key_raises(self):
        tracker = _make_tracker_with_budget()
        with pytest.raises(ProviderConfigurationError, match="Missing GEMINI_API_KEY"):
            GeminiProvider(api_key="", model="gemini-2.0-flash", tracker=tracker)

    @patch("content_engine.providers.gemini.provider.genai.Client")
    def test_successful_init(self, mock_client_class):
        tracker = _make_tracker_with_budget()
        mock_client_class.return_value = MagicMock()
        provider = GeminiProvider(
            api_key="test-key", model="gemini-2.0-flash", tracker=tracker
        )
        assert provider._model == "gemini-2.0-flash"
        mock_client_class.assert_called_once_with(api_key="test-key")

    @patch("content_engine.providers.gemini.provider.genai.Client")
    def test_api_key_not_stored_as_attribute(self, mock_client_class):
        tracker = _make_tracker_with_budget()
        mock_client_class.return_value = MagicMock()
        provider = GeminiProvider(
            api_key="secret-key", model="gemini-2.0-flash", tracker=tracker
        )
        assert not hasattr(provider, "api_key")


# --- Successful generation tests ---


class TestSuccessfulGeneration:
    @patch("content_engine.providers.gemini.provider.genai.Client")
    @pytest.mark.asyncio
    async def test_generate_returns_text(self, mock_client_class):
        tracker = _make_tracker_with_budget()
        mock_client_class.return_value = _make_mock_client(
            MockGenerationResponse(text="Hello, world!")
        )
        provider = GeminiProvider(
            api_key="test-key", model="gemini-2.0-flash", tracker=tracker
        )
        result = await provider.generate("Say hello", operation="brief")
        assert result.text == "Hello, world!"

    @patch("content_engine.providers.gemini.provider.genai.Client")
    @pytest.mark.asyncio
    async def test_generate_preserves_provider_metadata(self, mock_client_class):
        tracker = _make_tracker_with_budget()
        mock_client_class.return_value = _make_mock_client(
            MockGenerationResponse(text="Generated script content")
        )
        provider = GeminiProvider(
            api_key="test-key", model="gemini-2.0-flash", tracker=tracker
        )
        result = await provider.generate("Write a script", operation="script")
        assert result.provider == PROVIDER_NAME
        assert result.model == "gemini-2.0-flash"
        assert result.operation == "script"

    @patch("content_engine.providers.gemini.provider.genai.Client")
    @pytest.mark.asyncio
    async def test_generate_preserves_content_id(self, mock_client_class):
        tracker = _make_tracker_with_budget()
        mock_client_class.return_value = _make_mock_client(
            MockGenerationResponse(text="content")
        )
        provider = GeminiProvider(
            api_key="test-key", model="gemini-2.0-flash", tracker=tracker
        )
        cid = uuid4()
        result = await provider.generate(
            "prompt", operation="brief", content_id=str(cid)
        )
        assert result.content_id == str(cid)

    @patch("content_engine.providers.gemini.provider.genai.Client")
    @pytest.mark.asyncio
    async def test_generate_returns_generation_result(self, mock_client_class):
        tracker = _make_tracker_with_budget()
        mock_client_class.return_value = _make_mock_client(
            MockGenerationResponse(text="result text")
        )
        provider = GeminiProvider(
            api_key="test-key", model="gemini-2.0-flash", tracker=tracker
        )
        result = await provider.generate("prompt", operation="brief")
        assert isinstance(result, GenerationResult)

    @patch("content_engine.providers.gemini.provider.genai.Client")
    @pytest.mark.asyncio
    async def test_warning_allows_generation(self, mock_client_class):
        budget = ProviderBudget(
            provider=PROVIDER_NAME,
            period=BudgetPeriod.DAILY,
            official_limit=None,
            local_budget=100,
            warning_threshold=80,
            hard_stop_threshold=100,
            reserve=20,
        )
        budget.current_usage = 75
        tracker = BudgetTracker({PROVIDER_NAME: budget})
        mock_client_class.return_value = _make_mock_client(
            MockGenerationResponse(text="ok")
        )
        provider = GeminiProvider(
            api_key="test-key", model="gemini-2.0-flash", tracker=tracker
        )
        result = await provider.generate("prompt", operation="brief")
        assert result.text == "ok"


# --- Budget enforcement tests ---


class TestBudgetEnforcement:
    @patch("content_engine.providers.gemini.provider.genai.Client")
    @pytest.mark.asyncio
    async def test_budget_check_before_api_call(self, mock_client_class):
        tracker = _make_tracker_with_budget()
        mock_client_class.return_value = _make_mock_client(
            MockGenerationResponse(text="response")
        )
        provider = GeminiProvider(
            api_key="test-key", model="gemini-2.0-flash", tracker=tracker
        )
        await provider.generate("prompt", operation="brief")
        mock_client_class.return_value.aio.models.generate_content.assert_called_once()

    def test_no_budget_blocks_generation(self):
        tracker = _make_no_budget_tracker()
        provider = GeminiProvider.__new__(GeminiProvider)
        provider._model = "gemini-2.0-flash"
        provider._tracker = tracker

        with pytest.raises(ProviderConfigurationError, match="No local budget configured"):
            import asyncio

            asyncio.run(provider.generate("prompt", operation="brief"))

    def test_hard_stop_blocks_generation(self):
        tracker = _make_hard_stop_tracker()
        provider = GeminiProvider.__new__(GeminiProvider)
        provider._model = "gemini-2.0-flash"
        provider._tracker = tracker

        with pytest.raises(ProviderConfigurationError, match="Hard stop"):
            import asyncio

            asyncio.run(provider.generate("prompt", operation="brief"))

    @patch("content_engine.providers.gemini.provider.genai.Client")
    @pytest.mark.asyncio
    async def test_hard_stop_on_token_dimension_blocks(self, mock_client_class):
        """When a prior call exhausted the token budget, subsequent calls are blocked
        even if the request dimension still has headroom.
        """
        tracker = _make_tracker_with_budget(local_budget=100)
        # Simulate: 1 request used, 100 tokens used (token budget exhausted)
        tracker.record_usage(
            PROVIDER_NAME, units=1, operation="prior", model="gemini-2.0-flash"
        )
        tracker.record_usage(
            PROVIDER_NAME,
            units=100,
            operation="prior",
            model="gemini-2.0-flash",
            unit_type="tokens",
            force=True,
        )

        mock_client_class.return_value = _make_mock_client(
            MockGenerationResponse(text="should not happen")
        )
        provider = GeminiProvider(
            api_key="test-key", model="gemini-2.0-flash", tracker=tracker
        )
        with pytest.raises(ProviderConfigurationError, match="Hard stop"):
            await provider.generate("prompt", operation="brief")

        mock_client_class.return_value.aio.models.generate_content.assert_not_called()


# --- Usage accounting tests ---


class TestUsageRecording:
    @patch("content_engine.providers.gemini.provider.genai.Client")
    @pytest.mark.asyncio
    async def test_records_usage_when_available(self, mock_client_class):
        tracker = _make_tracker_with_budget()
        mock_client_class.return_value = _make_mock_client(
            MockGenerationResponse(
                text="response",
                usage=MockUsageMetadata(prompt=10, candidates=20, total=30),
            )
        )
        provider = GeminiProvider(
            api_key="test-key", model="gemini-2.0-flash", tracker=tracker
        )
        await provider.generate("prompt", operation="brief")
        records = tracker.usage_records()
        token_records = [r for r in records if r.unit_type == "tokens"]
        request_records = [r for r in records if r.unit_type == "requests"]

        assert len(token_records) == 1
        assert token_records[0].units == 30
        assert token_records[0].provider == PROVIDER_NAME
        assert token_records[0].model == "gemini-2.0-flash"
        assert token_records[0].operation == "brief"

        assert len(request_records) == 1
        assert request_records[0].units == 1
        assert request_records[0].unit_type == "requests"

    @patch("content_engine.providers.gemini.provider.genai.Client")
    @pytest.mark.asyncio
    async def test_no_usage_metadata_no_fabricated_usage(self, mock_client_class):
        tracker = _make_tracker_with_budget()
        mock_client_class.return_value = _make_mock_client(
            MockGenerationResponse(text="response", usage=None)
        )
        provider = GeminiProvider(
            api_key="test-key", model="gemini-2.0-flash", tracker=tracker
        )
        result = await provider.generate("prompt", operation="brief")
        assert result.usage is None
        token_records = [
            r for r in tracker.usage_records() if r.unit_type == "tokens"
        ]
        assert len(token_records) == 0

    @patch("content_engine.providers.gemini.provider.genai.Client")
    @pytest.mark.asyncio
    async def test_usage_not_recorded_if_zero_tokens(self, mock_client_class):
        tracker = _make_tracker_with_budget()
        mock_client_class.return_value = _make_mock_client(
            MockGenerationResponse(
                text="response",
                usage=MockUsageMetadata(prompt=0, candidates=0, total=0),
            )
        )
        provider = GeminiProvider(
            api_key="test-key", model="gemini-2.0-flash", tracker=tracker
        )
        await provider.generate("prompt", operation="brief")
        token_records = [
            r for r in tracker.usage_records() if r.unit_type == "tokens"
        ]
        assert len(token_records) == 0

    @patch("content_engine.providers.gemini.provider.genai.Client")
    @pytest.mark.asyncio
    async def test_excess_token_usage_recorded_and_blocks_future(self, mock_client_class):
        """A successful call whose token usage exceeds the remaining budget must:
        1. Still record the actual token usage.
        2. Leave the budget exhausted (token dimension at hard stop).
        3. Block subsequent Gemini generation.
        """
        tracker = _make_tracker_with_budget(local_budget=5)

        mock_client_class.return_value = _make_mock_client(
            MockGenerationResponse(
                text="generated despite budget",
                usage=MockUsageMetadata(prompt=20, candidates=30, total=50),
            )
        )
        provider = GeminiProvider(
            api_key="test-key", model="gemini-2.0-flash", tracker=tracker
        )
        result = await provider.generate("prompt", operation="brief")
        assert result.text == "generated despite budget"

        token_records = [
            r for r in tracker.usage_records() if r.unit_type == "tokens"
        ]
        assert len(token_records) == 1
        assert token_records[0].units == 50

        # Subsequent call must be blocked because token dimension is exhausted
        with pytest.raises(ProviderConfigurationError, match="Hard stop"):
            await provider.generate("prompt", operation="brief")


# --- Error handling tests ---


class TestErrorHandling:
    @patch("content_engine.providers.gemini.provider.genai.Client")
    @pytest.mark.asyncio
    async def test_api_error_translated(self, mock_client_class):
        tracker = _make_tracker_with_budget()
        mock_client_class.return_value = MagicMock()
        mock_client_class.return_value.aio.models.generate_content = AsyncMock(
            side_effect=_make_api_error(500, "internal server error")
        )

        provider = GeminiProvider(
            api_key="test-key", model="gemini-2.0-flash", tracker=tracker
        )
        with pytest.raises(ProviderAPIError, match="API error"):
            await provider.generate("prompt", operation="brief")

    @patch("content_engine.providers.gemini.provider.genai.Client")
    @pytest.mark.asyncio
    async def test_rate_limit_translated(self, mock_client_class):
        tracker = _make_tracker_with_budget()
        mock_client_class.return_value = MagicMock()
        mock_client_class.return_value.aio.models.generate_content = AsyncMock(
            side_effect=_make_api_error(429, "rate limit exceeded")
        )

        provider = GeminiProvider(
            api_key="test-key", model="gemini-2.0-flash", tracker=tracker
        )
        with pytest.raises(ProviderQuotaError, match="Rate limit"):
            await provider.generate("prompt", operation="brief")

    @patch("content_engine.providers.gemini.provider.genai.Client")
    @pytest.mark.asyncio
    async def test_auth_error_translated(self, mock_client_class):
        tracker = _make_tracker_with_budget()
        mock_client_class.return_value = MagicMock()
        mock_client_class.return_value.aio.models.generate_content = AsyncMock(
            side_effect=_make_api_error(401, "invalid api key")
        )

        provider = GeminiProvider(
            api_key="test-key", model="gemini-2.0-flash", tracker=tracker
        )
        with pytest.raises(ProviderConfigurationError, match="Authentication"):
            await provider.generate("prompt", operation="brief")

    @patch("content_engine.providers.gemini.provider.genai.Client")
    @pytest.mark.asyncio
    async def test_api_failure_does_not_record_usage(self, mock_client_class):
        """If the API call fails, no usage should be recorded."""
        tracker = _make_tracker_with_budget()
        mock_client_class.return_value = MagicMock()
        mock_client_class.return_value.aio.models.generate_content = AsyncMock(
            side_effect=_make_api_error(500, "server error")
        )

        provider = GeminiProvider(
            api_key="test-key", model="gemini-2.0-flash", tracker=tracker
        )
        with pytest.raises(ProviderAPIError):
            await provider.generate("prompt", operation="brief")

        assert len(tracker.usage_records()) == 0


# --- Provider protocol tests ---


class TestProviderProtocol:
    @patch("content_engine.providers.gemini.provider.genai.Client")
    @pytest.mark.asyncio
    async def test_gemini_provider_implements_protocol(self, mock_client_class):
        tracker = _make_tracker_with_budget()
        mock_client_class.return_value = _make_mock_client(
            MockGenerationResponse(text="hi")
        )
        provider = GeminiProvider(
            api_key="test-key", model="gemini-2.0-flash", tracker=tracker
        )
        assert isinstance(provider, TextGenerationProvider)

    @patch("content_engine.providers.gemini.provider.genai.Client")
    @pytest.mark.asyncio
    async def test_generate_is_coroutine_function(self, mock_client_class):
        import inspect

        tracker = _make_tracker_with_budget()
        mock_client_class.return_value = _make_mock_client(
            MockGenerationResponse(text="hi")
        )
        provider = GeminiProvider(
            api_key="test-key", model="gemini-2.0-flash", tracker=tracker
        )
        assert inspect.iscoroutinefunction(provider.generate)

    @patch("content_engine.providers.gemini.provider.genai.Client")
    @pytest.mark.asyncio
    async def test_no_raw_sdk_objects_in_result(self, mock_client_class):
        tracker = _make_tracker_with_budget()
        mock_client_class.return_value = _make_mock_client(
            MockGenerationResponse(
                text="response",
                usage=MockUsageMetadata(prompt=10, candidates=20, total=30),
            )
        )
        provider = GeminiProvider(
            api_key="test-key", model="gemini-2.0-flash", tracker=tracker
        )
        result = await provider.generate("prompt", operation="brief")
        assert isinstance(result, GenerationResult)
        assert type(result.usage) is GenerationUsage


# --- End-to-end: YAML config → load_budgets_from_config → GeminiProvider ---


class TestEndToEndConfigFlow:
    """Tests the complete YAML → BudgetTracker → GeminiProvider pipeline."""

    def _load_config(self, requests_per_day: int, tokens_per_day: int) -> BudgetTracker:
        config = {
            "budgets": {
                "gemini": {
                    "model": "gemini-2.0-flash",
                    "period": "daily",
                    "official_limit": None,
                    "local_budget": {
                        "requests_per_day": requests_per_day,
                        "tokens_per_day": tokens_per_day,
                    },
                    "warning_percent": 80,
                    "hard_stop_percent": 100,
                    "reserve_percent": 20,
                    "paid_fallback": False,
                }
            }
        }
        budgets = load_budgets_from_config(config)
        return BudgetTracker(budgets)

    @patch("content_engine.providers.gemini.provider.genai.Client")
    @pytest.mark.asyncio
    async def test_two_generations_then_request_exhausted(self, mock_client_class):
        """Config: requests=2, tokens=100.

        Gen1: +1 request, +40 tokens → succeeds
        Gen2: +1 request, +50 tokens → succeeds
        Gen3: request budget exhausted → blocked before API call
        """
        tracker = self._load_config(requests_per_day=3, tokens_per_day=100)
        mock_client_class.return_value = _make_mock_client(
            MockGenerationResponse(text="gen")
        )
        provider = GeminiProvider(
            api_key="test-key", model="gemini-2.0-flash", tracker=tracker
        )

        # Gen1
        mock_client_class.return_value.aio.models.generate_content = AsyncMock(
            return_value=MockGenerationResponse(
                text="gen1", usage=MockUsageMetadata(prompt=20, candidates=20, total=40)
            )
        )
        result1 = await provider.generate("p1", operation="brief")
        assert result1.text == "gen1"

        # Gen2
        mock_client_class.return_value.aio.models.generate_content = AsyncMock(
            return_value=MockGenerationResponse(
                text="gen2", usage=MockUsageMetadata(prompt=25, candidates=25, total=50)
            )
        )
        result2 = await provider.generate("p2", operation="brief")
        assert result2.text == "gen2"

        # Verify budget state
        budget = tracker.get_budget("gemini")
        assert budget is not None
        assert budget.current_usage == 2  # 2 requests
        assert budget.usage_by_unit_type["tokens"] == 90  # 40 + 50

        # Gen3: request budget exhausted (2/2), should be blocked before API call
        mock_client_class.return_value.aio.models.generate_content = AsyncMock(
            return_value=MockGenerationResponse(text="should not happen")
        )
        with pytest.raises(ProviderConfigurationError, match="Hard stop"):
            await provider.generate("p3", operation="brief")

        mock_client_class.return_value.aio.models.generate_content.assert_not_called()

    @patch("content_engine.providers.gemini.provider.genai.Client")
    @pytest.mark.asyncio
    async def test_excess_tokens_recorded_and_blocks_subsequent(self, mock_client_class):
        """Config: requests=10, tokens=100.

        Generation consumes 120 tokens (exceeds token budget):
        - API succeeds
        - 120 tokens MUST be recorded (force=True)
        - Subsequent token-budget check blocks further generation
        """
        tracker = self._load_config(requests_per_day=10, tokens_per_day=100)
        mock_client_class.return_value = _make_mock_client(
            MockGenerationResponse(text="ok")
        )

        mock_client_class.return_value.aio.models.generate_content = AsyncMock(
            return_value=MockGenerationResponse(
                text="generated",
                usage=MockUsageMetadata(prompt=60, candidates=60, total=120),
            )
        )
        provider = GeminiProvider(
            api_key="test-key", model="gemini-2.0-flash", tracker=tracker
        )
        result = await provider.generate("prompt", operation="brief")
        assert result.text == "generated"

        # Token usage must be recorded
        budget = tracker.get_budget("gemini")
        assert budget is not None
        assert budget.usage_by_unit_type["tokens"] == 120

        # Request usage must be recorded
        assert budget.current_usage == 1

        # Subsequent generation blocked by token dimension
        mock_client_class.return_value.aio.models.generate_content = AsyncMock(
            return_value=MockGenerationResponse(text="should not happen")
        )
        with pytest.raises(ProviderConfigurationError, match="Hard stop"):
            await provider.generate("prompt", operation="brief")

    @patch("content_engine.providers.gemini.provider.genai.Client")
    @pytest.mark.asyncio
    async def test_null_budget_from_yaml_blocks_all(self, mock_client_class):
        """Default YAML with null local_budget dict must block all Gemini generation."""
        config = {
            "budgets": {
                "gemini": {
                    "model": "gemini-2.0-flash",
                    "period": "provider-defined",
                    "official_limit": {
                        "requests_per_day": None,
                        "tokens_per_day": None,
                    },
                    "local_budget": {
                        "requests_per_day": None,
                        "tokens_per_day": None,
                    },
                    "paid_fallback": False,
                }
            }
        }
        budgets = load_budgets_from_config(config)
        budget = budgets["gemini"]
        assert budget.local_budget is None
        assert budget.local_budget_by_unit_type == {}
        assert budget.paid_fallback is False

        tracker = BudgetTracker(budgets)
        provider = GeminiProvider.__new__(GeminiProvider)
        provider._model = "gemini-2.0-flash"
        provider._tracker = tracker

        with pytest.raises(ProviderConfigurationError, match="No local budget configured"):
            await provider.generate("prompt", operation="brief")

    @patch("content_engine.providers.gemini.provider.genai.Client")
    @pytest.mark.asyncio
    async def test_config_dimensions_independent(self, mock_client_class):
        """Verify requests and tokens are tracked in separate counters."""
        tracker = self._load_config(requests_per_day=10, tokens_per_day=100)

        # Trigger threshold computation via check_allowance
        tracker.check_allowance(
            "gemini", units=1, unit_type="requests", model="gemini-2.0-flash"
        )

        budget = tracker.get_budget("gemini")
        assert budget is not None
        assert budget.local_budget_by_unit_type["requests"] == 10
        assert budget.local_budget_by_unit_type["tokens"] == 100
        assert budget.hard_stop_threshold_by_unit_type["requests"] == 10
        assert budget.hard_stop_threshold_by_unit_type["tokens"] == 100

        # Record 10 requests, 0 tokens → request check blocks, token check OK
        tracker.record_usage(
            "gemini", units=10, operation="x", model="m", unit_type="requests", force=True
        )
        token_result = tracker.check_allowance(
            "gemini", units=1, unit_type="tokens", model="m"
        )
        request_result = tracker.check_allowance(
            "gemini", units=1, unit_type="requests", model="m"
        )
        assert token_result.status == BudgetStatus.OK
        assert request_result.status == BudgetStatus.HARD_STOP
