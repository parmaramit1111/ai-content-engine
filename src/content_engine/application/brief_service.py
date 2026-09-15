"""Content brief generation service — produces validated briefs from topic + research.

Implements the Phase 07 content-brief vertical slice:

    Topic + ResearchNotes
        → BriefService.generate_brief()
        → TextGenerationProvider.generate()
        → GenerationResult (text = JSON)
        → JSON parsing + field validation
        → validated ContentBrief

The service is provider-agnostic: it depends on the
``TextGenerationProvider`` protocol only. No Gemini SDK types or
importable concrete provider classes are referenced.

Source references are never requested from the provider. They are taken
deterministically from ``Topic.source_refs`` and ``ResearchNotes.primary_sources``
so that ``ContentBrief.sources`` can never contain a fabricated reference
(ARCHITECTURE §21 — treat generated content as untrusted; PRD FR-10 — source
correctness is a human review concern, not something an LLM should invent).
"""

from __future__ import annotations

import json
from typing import Any

from content_engine.domain.models import ContentBrief, ResearchNotes, Topic
from content_engine.providers.base import TextGenerationProvider
from content_engine.providers.results import GenerationResult

_REQUIRED_FIELDS = (
    "problem",
    "core_explanation",
    "example",
    "takeaway",
    "cta",
    "estimated_duration",
    "visual_style",
)


class BriefServiceError(Exception):
    """Raised when content brief generation, parsing, or validation fails."""


class BriefService:
    """Generate structured content briefs from a topic and research via a text provider.

    The service constructs a deterministic prompt grounded in the topic and
    verified research, invokes the provider, parses the result, validates it,
    and returns a ``ContentBrief``. ``topic`` (title) and ``sources`` are set
    deterministically from the inputs rather than requested from the provider.

    No persistence is performed — the service operates in memory.

    Args:
        provider: Any ``TextGenerationProvider`` implementation.
    """

    def __init__(self, provider: TextGenerationProvider):
        self._provider = provider

    async def generate_brief(
        self,
        topic: Topic,
        research: ResearchNotes,
    ) -> ContentBrief:
        """Generate a validated ContentBrief from a Topic and its ResearchNotes.

        Args:
            topic: The Topic this brief is for (provides category, audience,
                difficulty, hook, title, and source_refs).
            research: Verified research supporting the topic (provides key
                facts, terminology, examples, caveats, visual concepts, and
                primary_sources).

        Returns:
            A validated ContentBrief.

        Raises:
            BriefServiceError: If ``research`` belongs to a different topic,
                or if the provider call, JSON parsing, or field validation
                fails.
        """
        if research.topic_id != topic.id:
            raise BriefServiceError(
                f"Research {research.id} belongs to topic {research.topic_id}, "
                f"not the requested topic {topic.id}"
            )

        prompt = self._build_prompt(topic, research)

        try:
            result: GenerationResult = await self._provider.generate(
                prompt,
                operation="brief",
                content_id=str(topic.id),
            )
        except Exception as exc:
            raise BriefServiceError(f"Content brief generation failed: {exc}") from exc

        return self._parse_and_validate(result, topic, research)

    def _build_prompt(self, topic: Topic, research: ResearchNotes) -> str:
        """Build the deterministic prompt defining the JSON contract."""
        return f"""You are an AI content strategist for a technical short-form video
creation pipeline. Generate a structured content brief as JSON.

Topic:
- Title: {topic.title}
- Category: {topic.category}
- Audience: {topic.audience}
- Difficulty: {topic.difficulty}
- Hook: {topic.hook}

Verified research:
- Key facts: {"; ".join(research.key_facts)}
- Terminology: {"; ".join(research.terminology)}
- Examples: {"; ".join(research.examples)}
- Caveats: {"; ".join(research.caveats)}
- Visual concepts: {"; ".join(research.visual_concepts)}

Requirements:
1. Output MUST be a JSON object with exactly these keys:
   - "problem": string (the problem/context this video addresses)
   - "core_explanation": string (core technical explanation, grounded ONLY
     in the research above)
   - "example": string (a concrete example)
   - "takeaway": string (the key takeaway)
   - "cta": string (a short call to action)
   - "estimated_duration": integer (seconds, suitable for a 20-60s short)
   - "visual_style": string (a short visual style description)
2. Do not invent facts beyond the research provided above.
3. Do not include source URLs or citations in any field; sources are
   attached separately by the pipeline.
4. Keep language concise and suitable for a 9:16 vertical video.

Return ONLY the JSON object, no additional text."""

    def _parse_and_validate(
        self,
        result: GenerationResult,
        topic: Topic,
        research: ResearchNotes,
    ) -> ContentBrief:
        """Parse the provider JSON response and validate into a ContentBrief.

        Raises:
            BriefServiceError: If JSON is malformed, required fields are
                missing, or values are structurally invalid.
        """
        try:
            data: Any = json.loads(result.text)
        except json.JSONDecodeError as exc:
            raise BriefServiceError(
                f"Failed to parse content brief JSON from provider response: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise BriefServiceError(
                f"Provider response must be a JSON object, got {type(data).__name__}"
            )

        missing = [field for field in _REQUIRED_FIELDS if field not in data]
        if missing:
            raise BriefServiceError(
                f"Provider response missing required field(s): {', '.join(missing)}"
            )

        return ContentBrief(
            topic=topic.title,
            problem=self._validate_string(data.get("problem"), "problem"),
            core_explanation=self._validate_string(
                data.get("core_explanation"), "core_explanation"
            ),
            example=self._validate_string(data.get("example"), "example"),
            takeaway=self._validate_string(data.get("takeaway"), "takeaway"),
            cta=self._validate_string(data.get("cta"), "cta"),
            sources=self._merge_sources(topic, research),
            estimated_duration=self._validate_duration(data.get("estimated_duration")),
            visual_style=self._validate_string(data.get("visual_style"), "visual_style"),
        )

    @staticmethod
    def _merge_sources(topic: Topic, research: ResearchNotes) -> list[str]:
        """Merge topic and research source references, preserving order and de-duping.

        Sources are never taken from provider output — only from already
        recorded topic/research references (ARCHITECTURE §21).
        """
        sources: list[str] = []
        for ref in (*topic.source_refs, *research.primary_sources):
            if ref not in sources:
                sources.append(ref)
        return sources

    @staticmethod
    def _validate_string(value: Any, field_name: str) -> str:
        """Validate that a value is a non-empty string."""
        if value is None:
            raise BriefServiceError(f"{field_name} is missing")
        if not isinstance(value, str):
            raise BriefServiceError(f"{field_name} must be a string, got {type(value).__name__}")
        if not value.strip():
            raise BriefServiceError(f"{field_name} is empty")
        return value

    @staticmethod
    def _validate_duration(value: Any) -> int:
        """Validate that a value is a positive integer duration in seconds.

        Booleans are rejected even though ``bool`` is a subclass of ``int``
        in Python. Fractional floats are rejected rather than silently
        truncated; a whole-number float (e.g. ``45.0``) is normalized to
        ``int``.
        """
        if value is None:
            raise BriefServiceError("estimated_duration is missing")
        if isinstance(value, bool):
            raise BriefServiceError(
                f"estimated_duration must be an integer, got {type(value).__name__}"
            )
        if isinstance(value, float) and not value.is_integer():
            raise BriefServiceError(
                f"estimated_duration must be a whole number of seconds, got {value}"
            )
        try:
            duration = int(value)
        except (TypeError, ValueError) as exc:
            raise BriefServiceError(
                f"estimated_duration must be an integer, got {type(value).__name__}"
            ) from exc
        if duration < 1:
            raise BriefServiceError(f"estimated_duration must be >= 1, got {duration}")
        return duration
