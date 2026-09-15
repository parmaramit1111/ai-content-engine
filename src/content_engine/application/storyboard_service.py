"""Storyboard generation service — produces enriched visual prompts for a script.

Implements the Phase 08 storyboard vertical slice:

    Script + ContentBrief
        → StoryboardService.generate_storyboard()
        → TextGenerationProvider.generate()
        → GenerationResult (text = JSON: {number, visual_prompt} pairs)
        → JSON parsing + coverage validation
        → validated Storyboard (Script.scenes rebuilt with enriched visual_prompt)

The service is provider-agnostic: it depends on the
``TextGenerationProvider`` protocol only. No Gemini SDK types or
importable concrete provider classes are referenced. Google Flow is never
called — its output is not used programmatically anywhere in this module.

The provider controls only ``visual_prompt`` text, keyed by scene ``number``.
Every other scene field (``number``, ``duration``, ``narration``,
``onscreen_text``, ``transition``) is copied verbatim from the original
``Script.scenes`` and the final scene list is always rebuilt in the
original script's order — the provider's response is never used for
ordering or for any field but ``visual_prompt``, so it cannot redefine
scene count, order, or any script-owned field even if it tries to.
"""

from __future__ import annotations

import json
from typing import Any

from content_engine.domain.models import ContentBrief, Scene, Script, Storyboard
from content_engine.providers.base import TextGenerationProvider
from content_engine.providers.results import GenerationResult


class StoryboardServiceError(Exception):
    """Raised when storyboard generation, parsing, or validation fails."""


class StoryboardService:
    """Enrich a Script's per-scene visual prompts via a text provider.

    The service constructs a deterministic prompt grounded in the script's
    existing scenes and the brief's visual style, invokes the provider,
    validates the result, and returns a ``Storyboard`` whose scenes are the
    original ``Script.scenes`` with only ``visual_prompt`` replaced.

    No persistence, filesystem export, or Google Flow interaction is
    performed — the service operates in memory only.

    Args:
        provider: Any ``TextGenerationProvider`` implementation.
    """

    def __init__(self, provider: TextGenerationProvider):
        self._provider = provider

    async def generate_storyboard(
        self,
        script: Script,
        brief: ContentBrief,
    ) -> Storyboard:
        """Generate a validated Storyboard from a Script and its ContentBrief.

        Args:
            script: The validated Script whose scenes will be enriched.
            brief: The ContentBrief the script was generated from (provides
                topic, visual_style, and core_explanation for grounding).

        Returns:
            A validated Storyboard with scenes in the script's original order.

        Raises:
            StoryboardServiceError: If ``script`` belongs to a different
                brief, or if the provider call, JSON parsing, or field
                validation fails.
        """
        if script.brief_id != brief.id:
            raise StoryboardServiceError(
                f"Script {script.id} belongs to brief {script.brief_id}, "
                f"not the requested brief {brief.id}"
            )

        prompt = self._build_prompt(script, brief)

        try:
            result: GenerationResult = await self._provider.generate(
                prompt,
                operation="storyboard",
                content_id=str(script.id),
            )
        except Exception as exc:
            raise StoryboardServiceError(f"Storyboard generation failed: {exc}") from exc

        return self._parse_and_validate(result, script)

    def _build_prompt(self, script: Script, brief: ContentBrief) -> str:
        """Build the deterministic prompt defining the JSON contract."""
        scene_lines = []
        for scene in script.scenes:
            line = (
                f'- Scene {scene.number} ({scene.duration}s): '
                f'narration="{scene.narration}"; '
                f'current visual_prompt="{scene.visual_prompt}"'
            )
            if scene.onscreen_text:
                line += f'; onscreen_text="{scene.onscreen_text}"'
            scene_lines.append(line)
        scenes_context = "\n".join(scene_lines)
        valid_numbers = ", ".join(str(scene.number) for scene in script.scenes)

        return f"""You are an AI visual director for a technical short-form video
creation pipeline. Enrich the visual direction for each existing scene as JSON.

Video context:
- Topic: {brief.topic}
- Visual style: {brief.visual_style}
- Core explanation: {brief.core_explanation}

Existing scenes (do NOT change count, order, or numbers):
{scenes_context}

Requirements:
1. Output MUST be a JSON object: {{"scenes": [{{"number": <int>, "visual_prompt": <string>}}, ...]}}
2. You MUST return exactly one entry for each of these scene numbers, no
   more, no fewer: {valid_numbers}
3. Do not invent new scenes, renumber scenes, or omit any scene number.
4. Do not include narration, on-screen text, or duration — only "visual_prompt".
5. Each "visual_prompt" must be a concrete, detailed visual direction
   consistent with "{brief.visual_style}" across all scenes (consistent
   style, tone, and composition).
6. Ground each visual_prompt in that scene's existing narration; do not
   invent facts beyond what is given above.

Return ONLY the JSON object, no additional text."""

    def _parse_and_validate(self, result: GenerationResult, script: Script) -> Storyboard:
        """Parse the provider JSON response and rebuild scenes with enriched prompts.

        Raises:
            StoryboardServiceError: If JSON is malformed, scene coverage is
                incomplete/excessive, or a visual_prompt value is invalid.
        """
        try:
            data: Any = json.loads(result.text)
        except json.JSONDecodeError as exc:
            raise StoryboardServiceError(
                f"Failed to parse storyboard JSON from provider response: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise StoryboardServiceError(
                f"Provider response must be a JSON object, got {type(data).__name__}"
            )

        if "scenes" not in data:
            raise StoryboardServiceError("Provider response missing 'scenes' key")

        scenes_data = data["scenes"]
        if not isinstance(scenes_data, list):
            raise StoryboardServiceError("'scenes' must be an array")

        enriched_prompts = self._extract_enriched_prompts(scenes_data)
        self._validate_scene_coverage(enriched_prompts, script)

        rebuilt_scenes: list[Scene] = [
            scene.model_copy(update={"visual_prompt": enriched_prompts[scene.number]})
            for scene in script.scenes
        ]

        return Storyboard(script_id=script.id, scenes=rebuilt_scenes)

    def _extract_enriched_prompts(self, scenes_data: list[Any]) -> dict[int, str]:
        """Extract and validate {number: visual_prompt} pairs from the raw JSON list.

        Only ``number`` and ``visual_prompt`` are ever read from each entry;
        any other key the provider includes is ignored.
        """
        enriched: dict[int, str] = {}
        for i, item in enumerate(scenes_data):
            if not isinstance(item, dict):
                raise StoryboardServiceError(f"Scene entry at index {i} is not a dict")

            number = item.get("number")
            if not isinstance(number, int) or isinstance(number, bool):
                raise StoryboardServiceError(
                    f"Scene entry at index {i} has invalid 'number': {number!r}"
                )

            if number in enriched:
                raise StoryboardServiceError(f"Duplicate visual_prompt entry for scene {number}")

            visual_prompt = self._validate_string(
                item.get("visual_prompt"), f"Scene {number} visual_prompt"
            )
            enriched[number] = visual_prompt
        return enriched

    @staticmethod
    def _validate_scene_coverage(enriched: dict[int, str], script: Script) -> None:
        """Ensure the provider covered every script scene number, and no others."""
        expected = {scene.number for scene in script.scenes}
        actual = set(enriched.keys())

        missing = sorted(expected - actual)
        if missing:
            raise StoryboardServiceError(
                f"Provider response missing visual_prompt for scene(s): {missing}"
            )

        extra = sorted(actual - expected)
        if extra:
            raise StoryboardServiceError(
                f"Provider response contains unknown scene number(s): {extra}"
            )

    @staticmethod
    def _validate_string(value: Any, field_name: str) -> str:
        """Validate that a value is a non-empty string."""
        if value is None:
            raise StoryboardServiceError(f"{field_name} is missing")
        if not isinstance(value, str):
            raise StoryboardServiceError(
                f"{field_name} must be a string, got {type(value).__name__}"
            )
        if not value.strip():
            raise StoryboardServiceError(f"{field_name} is empty")
        return value
