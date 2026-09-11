"""Result models for text generation providers."""

from typing import Any

from pydantic import BaseModel, Field


class GenerationUsage(BaseModel):
    """Token usage for a single generation request.

    Fields are optional because not all providers or responses include
    usage metadata. When data is unavailable, None is used rather than
    fabricating estimates.
    """

    input_tokens: int | None = Field(
        default=None, description="Number of input tokens consumed"
    )
    output_tokens: int | None = Field(
        default=None, description="Number of output tokens generated"
    )
    total_tokens: int | None = Field(
        default=None, description="Total tokens (input + output) consumed"
    )


class GenerationResult(BaseModel):
    """Result of a text generation request.

    Designed to carry enough information for downstream workflows (briefs,
    scripts, storyboards, metadata) while keeping the provider boundary clean.
    Raw SDK response objects are never exposed here.
    """

    text: str = Field(description="Generated text content")
    provider: str = Field(description="Provider name (e.g. 'gemini')")
    model: str = Field(description="Model name used for generation")
    operation: str = Field(description="Operation type (e.g. 'brief', 'script')")
    content_id: str | None = Field(
        default=None, description="Content/workflow identifier when supplied"
    )
    usage: GenerationUsage | None = Field(
        default=None, description="Token usage when available from the provider"
    )
    metadata: dict[str, Any] | None = Field(
        default=None, description="Additional provider-specific metadata (sanitized)"
    )
