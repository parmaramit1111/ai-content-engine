"""Gemini text generation provider (ARCHITECTURE §7, §4.2).

Uses the official `google-genai` SDK (google.genai), imported as:

    from google import genai
    from google.genai import errors as genai_errors

The Google Gen AI SDK reached GA in May 2025 and is the current recommended
SDK. `google-generativeai` is deprecated (EOL November 2025).

This provider integrates with the existing BudgetTracker to enforce local
safety budgets before any API call is made. Request counts and token counts
are tracked as separate dimensions via the ``unit_type`` parameter.
"""

from uuid import UUID

from google import genai
from google.genai import errors as genai_errors

from content_engine.budgets.models import BudgetStatus
from content_engine.budgets.tracker import BudgetTracker
from content_engine.providers.exceptions import (
    ProviderAPIError,
    ProviderConfigurationError,
    ProviderQuotaError,
)
from content_engine.providers.results import GenerationResult, GenerationUsage

PROVIDER_NAME = "gemini"


class GeminiProvider:
    """Gemini text generation provider with budget enforcement.

    The provider checks local budget allowances before making any API call.
    By default (null local_budget in config), automated Gemini generation is
    blocked until an explicit local budget is configured (PRD §8.2).

    Args:
        api_key: Gemini API key from environment (GEMINI_API_KEY).
        model: Model name from configuration (GEMINI_MODEL).
        tracker: BudgetTracker instance with configured provider budgets.
    """

    def __init__(
        self,
        api_key: str | None,
        model: str,
        tracker: BudgetTracker,
    ):
        if not api_key:
            raise ProviderConfigurationError(
                message="Missing GEMINI_API_KEY environment variable",
                provider=PROVIDER_NAME,
                model=model,
            )

        self._model = model
        self._tracker = tracker
        self._client = genai.Client(api_key=api_key)

    async def generate(
        self,
        prompt: str,
        *,
        operation: str,
        content_id: str | None = None,
    ) -> GenerationResult:
        """Generate text from Gemini, enforcing budget before the call.

        Budget enforcement:
            1. Pre-check request dimension: block if NO_BUDGET or HARD_STOP.
            2. Pre-check token dimension: block if HARD_STOP (token budget
               exhausted from a prior call whose usage was recorded).
            3. Make the API call.
            4. Post-record request usage (1 unit) with ``force=True``.
            5. Post-record token usage (actual token count) with ``force=True``
               so the consumption is always accounted for even if it exceeds
               the remaining budget — the API call has already succeeded.

        Args:
            prompt: The input prompt text.
            operation: What operation this generation supports.
            content_id: Optional content/workflow identifier.

        Returns:
            GenerationResult with generated text and metadata.

        Raises:
            ProviderConfigurationError: Missing API key, invalid model,
                budget not configured, or hard stop.
            ProviderQuotaError: Rate limit or quota exceeded.
            ProviderAPIError: Other API or network failure.
        """
        self._check_budget(operation, content_id)

        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt,
            )
        except genai_errors.APIError as exc:
            raise self._translate_api_error(exc) from exc

        text = response.text or ""

        usage = None
        if response.usage_metadata is not None:
            usage = GenerationUsage(
                input_tokens=response.usage_metadata.prompt_token_count,
                output_tokens=response.usage_metadata.candidates_token_count,
                total_tokens=response.usage_metadata.total_token_count,
            )

        self._record_usage(operation, content_id, usage)

        return GenerationResult(
            text=text,
            provider=PROVIDER_NAME,
            model=self._model,
            operation=operation,
            content_id=content_id,
            usage=usage,
        )

    def _check_budget(self, operation: str, content_id: str | None) -> None:
        """Pre-check both request and token budget dimensions.

        Raises ProviderConfigurationError if either dimension is not
        configured (NO_BUDGET) or exhausted (HARD_STOP).
        """
        for unit_type in ("requests", "tokens"):
            check_result = self._tracker.check_allowance(
                PROVIDER_NAME,
                units=1,
                operation=operation,
                model=self._model,
                unit_type=unit_type,
            )

            if check_result.status == BudgetStatus.NO_BUDGET:
                raise ProviderConfigurationError(
                    message=(
                        f"No local budget configured for '{PROVIDER_NAME}'. "
                        f"Automated work is not permitted until a local_budget is set "
                        f"in the budget configuration."
                    ),
                    provider=PROVIDER_NAME,
                    model=self._model,
                )

            if check_result.status == BudgetStatus.HARD_STOP:
                raise ProviderConfigurationError(
                    message=(
                        f"Hard stop: {PROVIDER_NAME} budget exhausted "
                        f"({check_result.current_usage}/{check_result.local_budget} "
                        f"used, requesting 1 -> projected {check_result.projected_usage})."
                    ),
                    provider=PROVIDER_NAME,
                    model=self._model,
                )

    def _record_usage(
        self,
        operation: str,
        content_id: str | None,
        usage: GenerationUsage | None,
    ) -> None:
        """Record actual usage after a successful API call.

        Uses ``force=True`` because the resource has already been consumed:
        the actual token count is only known post-call, and the usage must
        be accounted for even if it exceeds the remaining budget.
        """
        parsed_content_id = self._parse_content_id(content_id)

        self._tracker.record_usage(
            PROVIDER_NAME,
            units=1,
            operation=operation,
            content_id=parsed_content_id,
            model=self._model,
            unit_type="requests",
            force=True,
        )

        if usage is not None:
            units = usage.total_tokens or 0
            if units > 0:
                self._tracker.record_usage(
                    PROVIDER_NAME,
                    units=units,
                    operation=operation,
                    content_id=parsed_content_id,
                    model=self._model,
                    unit_type="tokens",
                    force=True,
                )

    def _translate_api_error(self, exc: genai_errors.APIError) -> Exception:
        """Translate a Google GenAI APIError into a provider exception."""
        message = str(exc.message) if exc.message else str(exc)

        if exc.code == 429:
            return ProviderQuotaError(
                message=f"Rate limit or quota exceeded: {message}",
                provider=PROVIDER_NAME,
                model=self._model,
            )

        if exc.code in (401, 403):
            return ProviderConfigurationError(
                message=f"Authentication/authorization failure: {message}",
                provider=PROVIDER_NAME,
                model=self._model,
            )

        return ProviderAPIError(
            message=f"API error ({exc.code}): {message}",
            provider=PROVIDER_NAME,
            model=self._model,
        )

    @staticmethod
    def _parse_content_id(content_id: str | None) -> UUID | None:
        """Convert a string content_id to UUID for ProviderUsage tracking.

        Returns None if content_id is None or not a valid UUID string.
        Non-UUID identifiers should be passed via metadata instead.
        """
        if content_id is None:
            return None
        try:
            return UUID(content_id)
        except (ValueError, AttributeError):
            return None
