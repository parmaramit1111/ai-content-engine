"""Script generation service — produces validated scripts from briefs.

Implements the content-generation vertical slice:

    ContentBrief
        → ScriptService.generate_script()
        → TextGenerationProvider.generate()
        → GenerationResult (text = JSON)
        → JSON parsing + Pydantic validation
        → validated Script / Scene objects

The service is provider-agnostic: it depends on the
``TextGenerationProvider`` protocol only. No Gemini SDK types or
importable concrete provider classes are referenced.
"""

from __future__ import annotations

import json
from typing import Any

from content_engine.domain.models import ContentBrief, Scene, Script
from content_engine.providers.base import TextGenerationProvider
from content_engine.providers.results import GenerationResult


class ScriptServiceError(Exception):
    """Raised when script generation, parsing, or validation fails."""


class ScriptService:
    """Generate structured scripts from content briefs via a text provider.

    The service constructs a deterministic prompt defining the expected
    JSON contract, invokes the provider, parses the result, validates it
    through Pydantic models, and returns a ``Script`` containing validated
    ``Scene`` objects.

    No persistence is performed — the service operates in memory.

    Args:
        provider: Any ``TextGenerationProvider`` implementation.
    """

    def __init__(self, provider: TextGenerationProvider):
        self._provider = provider

    async def generate_script(
        self,
        brief: ContentBrief,
        version: int = 1,
    ) -> Script:
        """Generate a validated Script from a ContentBrief.

        Args:
            brief: The ContentBrief describing the video concept.
            version: Script version number (starts at 1).

        Returns:
            A validated Script with ordered Scene objects.

        Raises:
            ScriptServiceError: If the provider call, JSON parsing,
                or structural validation fails.
        """
        prompt = self._build_prompt(brief)

        try:
            result: GenerationResult = await self._provider.generate(
                prompt,
                operation="script",
                content_id=str(brief.id),
            )
        except Exception as exc:
            raise ScriptServiceError(f"Script generation failed: {exc}") from exc

        return self._parse_and_validate(result, brief, version)

    def _build_prompt(self, brief: ContentBrief) -> str:
        """Build the deterministic prompt defining the JSON contract."""
        return f"""You are an AI scriptwriter for a technical short-form video
creation pipeline. Generate a structured script as JSON.

Video brief:
- Topic: {brief.topic}
- Problem: {brief.problem}
- Core explanation: {brief.core_explanation}
- Example: {brief.example}
- Takeaway: {brief.takeaway}
- CTA: {brief.cta}
- Estimated duration: {brief.estimated_duration} seconds
- Visual style: {brief.visual_style}

Requirements:
1. Output MUST be a JSON object with a "scenes" key containing an
   array of scene objects.
2. Each scene must have:
   - "number": integer (1-indexed, sequential)
   - "duration": float (seconds; total sums to ~{brief.estimated_duration}s)
   - "narration": string (voice-over text)
   - "visual_prompt": string (prompt for visual generation)
   - "onscreen_text": string or null
   - "transition": string or null

3. Total duration must be within 10% of {brief.estimated_duration}s.
4. Narration must be concise for 9:16 vertical video.
5. Structure: hook (0-3s), context (3-10s), explanation (10-45s),
   takeaway (45-55s), CTA (final seconds).

Return ONLY the JSON object, no additional text."""

    def _parse_and_validate(
        self,
        result: GenerationResult,
        brief: ContentBrief,
        version: int,
    ) -> Script:
        """Parse the provider JSON response and validate into a Script.

        Raises:
            ScriptServiceError: If JSON is malformed, required fields
                are missing, or values are structurally invalid.
        """
        try:
            data: dict[str, Any] = json.loads(result.text)
        except json.JSONDecodeError as exc:
            raise ScriptServiceError(
                f"Failed to parse script JSON from provider response: {exc}"
            ) from exc

        scenes_data = self._extract_scenes(data)
        scenes = self._build_scenes(scenes_data)

        if not scenes:
            raise ScriptServiceError("Provider returned an empty scenes list")

        self._validate_scene_sequence(scenes)

        return Script(
            brief_id=brief.id,
            version=version,
            scenes=scenes,
        )

    def _extract_scenes(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract and validate the scenes array from parsed JSON."""
        if "scenes" not in data:
            raise ScriptServiceError("Provider response missing 'scenes' key")
        scenes_data = data["scenes"]
        if not isinstance(scenes_data, list):
            raise ScriptServiceError("'scenes' must be an array")
        return scenes_data

    def _build_scenes(self, scenes_data: list[dict[str, Any]]) -> list[Scene]:
        """Construct Scene objects from raw JSON dicts with validation."""
        scenes: list[Scene] = []
        for i, scene_data in enumerate(scenes_data):
            if not isinstance(scene_data, dict):
                raise ScriptServiceError(f"Scene at index {i} is not a dict")

            number = scene_data.get("number", i + 1)
            duration = self._validate_number(scene_data.get("duration"), f"Scene {number} duration")
            narration = self._validate_string(
                scene_data.get("narration"), f"Scene {number} narration"
            )
            visual_prompt = self._validate_string(
                scene_data.get("visual_prompt"), f"Scene {number} visual_prompt"
            )

            scene = Scene(
                number=number,
                duration=duration,
                narration=narration,
                visual_prompt=visual_prompt,
                onscreen_text=scene_data.get("onscreen_text"),
                transition=scene_data.get("transition"),
            )
            scenes.append(scene)
        return scenes

    def _validate_scene_sequence(self, scenes: list[Scene]) -> None:
        """Ensure scene numbers are sequential starting from 1."""
        for i, scene in enumerate(scenes):
            if scene.number != i + 1:
                raise ScriptServiceError(
                    f"Scene at index {i} has number {scene.number}, "
                    f"expected {i + 1} (scenes must be sequential from 1)"
                )

    @staticmethod
    def _validate_number(value: Any, field_name: str) -> float:
        """Validate that a value is a non-negative number."""
        if value is None:
            raise ScriptServiceError(f"{field_name} is missing")
        try:
            num = float(value)
        except (TypeError, ValueError) as exc:
            raise ScriptServiceError(
                f"{field_name} must be a number, got {type(value).__name__}"
            ) from exc
        if num < 0:
            raise ScriptServiceError(f"{field_name} must be non-negative, got {num}")
        return num

    @staticmethod
    def _validate_string(value: Any, field_name: str) -> str:
        """Validate that a value is a non-empty string."""
        if value is None:
            raise ScriptServiceError(f"{field_name} is missing")
        if not isinstance(value, str):
            raise ScriptServiceError(f"{field_name} must be a string, got {type(value).__name__}")
        if not value.strip():
            raise ScriptServiceError(f"{field_name} is empty")
        return value
