"""Text generation provider abstraction (ARCHITECTURE §4.2).

The domain/application layer depends only on this Protocol. Concrete
implementations (e.g. GeminiProvider) sit behind this boundary so that
vendor-specific details never leak into domain logic.
"""

from typing import Protocol, runtime_checkable

from content_engine.providers.results import GenerationResult


@runtime_checkable
class TextGenerationProvider(Protocol):
    """Protocol for providers that generate text from a prompt.

    Implementations must be async-compatible since the Gemini SDK supports
    async operations natively (ARCHITECTURE §4.2).
    """

    async def generate(
        self,
        prompt: str,
        *,
        operation: str,
        content_id: str | None = None,
    ) -> GenerationResult:
        """Generate text from a prompt.

        Args:
            prompt: The input prompt text.
            operation: What operation this generation supports (e.g. "brief", "script").
            content_id: Optional identifier linking this generation to a content item.

        Returns:
            GenerationResult with the generated text and metadata.
        """
        ...
