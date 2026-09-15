"""Focused unit tests for the StoryboardService vertical slice.

Tests cover:
1.  valid generation request
2.  provider invocation (operation="storyboard", content_id)
3.  provider independence using a fake provider + full-module import scan
4.  deterministic prompt construction (script + brief grounding)
5.  structural-truth preservation: number/duration/narration/onscreen_text/
    transition are copied verbatim from the original script, even if the
    provider tries to override them — only visual_prompt is ever taken
    from provider output
6.  ordering independence: provider response order never affects output order
7.  script.brief_id / brief.id consistency check
8.  malformed JSON, non-dict response, missing/invalid 'scenes'
9.  invalid scene entries: non-dict, invalid number (missing/wrong-type/bool),
    duplicate number, missing/extra scene coverage, empty/non-string
    visual_prompt
10. provider configuration/quota/API/generic errors

No real Gemini API calls. Uses a fake TextGenerationProvider.
"""

import ast
import json
from inspect import getsource
from typing import Any
from uuid import uuid4

import pytest

from content_engine.application import storyboard_service as storyboard_service_module
from content_engine.application.storyboard_service import (
    StoryboardService,
    StoryboardServiceError,
)
from content_engine.domain.models import ContentBrief, Scene, Script, Storyboard
from content_engine.providers.results import GenerationResult


class FakeProvider:
    """Test double implementing TextGenerationProvider.

    Returns a configurable GenerationResult or raises an exception.
    """

    def __init__(
        self,
        text: str | None = None,
        exc: Exception | None = None,
    ):
        self.text = text
        self.exc = exc
        self.call_count = 0
        self.last_prompt = None
        self.last_operation = None
        self.last_content_id = None

    async def generate(
        self,
        prompt: str,
        *,
        operation: str,
        content_id: str | None = None,
    ) -> GenerationResult:
        self.call_count += 1
        self.last_prompt = prompt
        self.last_operation = operation
        self.last_content_id = content_id

        if self.exc is not None:
            raise self.exc

        return GenerationResult(
            text=self.text or "",
            provider="fake",
            model="fake-model",
            operation=operation,
            content_id=content_id,
        )


# Shared default so independently-built _make_script()/_make_brief() calls
# are linked by default; tests that need a mismatch pass an explicit brief_id.
_DEFAULT_BRIEF_ID = uuid4()


def _make_brief(**overrides: Any) -> ContentBrief:
    defaults = {
        "id": _DEFAULT_BRIEF_ID,
        "topic": "What is RAG?",
        "problem": "LLMs hallucinate without grounded context",
        "core_explanation": "RAG combines retrieval with generation",
        "example": "A chatbot fetching docs before answering",
        "takeaway": "RAG reduces hallucinations by grounding responses",
        "cta": "Try RAG in your next project",
        "estimated_duration": 45,
        "visual_style": "Clean diagrams, dark theme, 9:16 vertical",
    }
    defaults.update(overrides)
    return ContentBrief(**defaults)


def _make_scene(**overrides: Any) -> Scene:
    defaults: dict[str, Any] = {
        "number": 1,
        "duration": 5.0,
        "narration": "Hook narration",
        "visual_prompt": "placeholder visual",
    }
    defaults.update(overrides)
    return Scene(**defaults)


def _make_script(scenes: list[Scene] | None = None, **overrides: Any) -> Script:
    if scenes is None:
        scenes = [
            _make_scene(number=1, narration="Hook narration", visual_prompt="placeholder 1"),
            _make_scene(
                number=2,
                duration=40.0,
                narration="Explanation narration",
                visual_prompt="placeholder 2",
                onscreen_text="RAG",
                transition="cut",
            ),
        ]
    defaults: dict[str, Any] = {
        "brief_id": _DEFAULT_BRIEF_ID,
        "scenes": scenes,
    }
    defaults.update(overrides)
    return Script(**defaults)


def _valid_storyboard_json(script: Script) -> str:
    return json.dumps(
        {
            "scenes": [
                {
                    "number": scene.number,
                    "visual_prompt": f"Enriched visual for scene {scene.number}",
                }
                for scene in script.scenes
            ]
        }
    )


class TestStoryboardServiceInit:
    def test_service_stores_provider(self):
        provider = FakeProvider(text="{}")
        service = StoryboardService(provider)
        assert service._provider is provider


class TestStoryboardServiceGenerateStoryboard:
    @pytest.mark.asyncio
    async def test_valid_generation_request(self):
        script = _make_script()
        provider = FakeProvider(text=_valid_storyboard_json(script))
        service = StoryboardService(provider)
        brief = _make_brief()

        storyboard = await service.generate_storyboard(script, brief)

        assert isinstance(storyboard, Storyboard)
        assert storyboard.script_id == script.id
        assert len(storyboard.scenes) == 2
        assert storyboard.scenes[0].visual_prompt == "Enriched visual for scene 1"
        assert storyboard.scenes[1].visual_prompt == "Enriched visual for scene 2"

    @pytest.mark.asyncio
    async def test_provider_invocation(self):
        script = _make_script()
        provider = FakeProvider(text=_valid_storyboard_json(script))
        service = StoryboardService(provider)
        brief = _make_brief()

        await service.generate_storyboard(script, brief)

        assert provider.call_count == 1
        assert provider.last_operation == "storyboard"
        assert provider.last_content_id == str(script.id)

    def test_storyboard_service_is_provider_agnostic(self):
        """No import anywhere in the storyboard_service module may reference
        a concrete provider (e.g. Gemini/google.genai)."""
        tree = ast.parse(getsource(storyboard_service_module))
        imported_names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imported_names.append(module)
                imported_names.extend(f"{module}.{alias.name}" for alias in node.names)

        joined = " ".join(imported_names).lower()
        assert "gemini" not in joined
        assert "google" not in joined
        assert "flow" not in joined

    @pytest.mark.asyncio
    async def test_deterministic_prompt_construction(self):
        script = _make_script()
        provider = FakeProvider(text=_valid_storyboard_json(script))
        service = StoryboardService(provider)
        brief = _make_brief()

        await service.generate_storyboard(script, brief)

        prompt = provider.last_prompt
        assert brief.topic in prompt
        assert brief.visual_style in prompt
        assert brief.core_explanation in prompt
        assert script.scenes[0].narration in prompt
        assert script.scenes[1].narration in prompt
        assert "json" in prompt.lower()


class TestStoryboardServiceStructuralTruth:
    @pytest.mark.asyncio
    async def test_only_visual_prompt_is_taken_from_provider(self):
        """Bogus structural fields in the provider response must be ignored."""
        script = _make_script()
        text = json.dumps(
            {
                "scenes": [
                    {
                        "number": 1,
                        "visual_prompt": "Enriched visual for scene 1",
                        "narration": "HIJACKED NARRATION",
                        "duration": 999,
                        "onscreen_text": "HIJACKED",
                        "transition": "HIJACKED",
                    },
                    {"number": 2, "visual_prompt": "Enriched visual for scene 2"},
                ]
            }
        )
        provider = FakeProvider(text=text)
        service = StoryboardService(provider)
        brief = _make_brief()

        storyboard = await service.generate_storyboard(script, brief)

        scene1 = storyboard.scenes[0]
        assert scene1.narration == script.scenes[0].narration
        assert scene1.duration == script.scenes[0].duration
        assert scene1.onscreen_text == script.scenes[0].onscreen_text
        assert scene1.transition == script.scenes[0].transition
        assert scene1.visual_prompt == "Enriched visual for scene 1"

    @pytest.mark.asyncio
    async def test_scene_count_and_numbers_come_from_script_not_provider(self):
        """Even if the provider tried to add an extra scene, it is rejected,
        not silently appended (see coverage validation tests below); this
        test proves the happy-path output count always matches the script."""
        script = _make_script()
        provider = FakeProvider(text=_valid_storyboard_json(script))
        service = StoryboardService(provider)
        brief = _make_brief()

        storyboard = await service.generate_storyboard(script, brief)

        assert len(storyboard.scenes) == len(script.scenes)
        assert [s.number for s in storyboard.scenes] == [s.number for s in script.scenes]

    @pytest.mark.asyncio
    async def test_provider_response_order_does_not_affect_output_order(self):
        script = _make_script()
        # Reversed order in the provider's JSON array.
        text = json.dumps(
            {
                "scenes": [
                    {"number": 2, "visual_prompt": "Enriched visual for scene 2"},
                    {"number": 1, "visual_prompt": "Enriched visual for scene 1"},
                ]
            }
        )
        provider = FakeProvider(text=text)
        service = StoryboardService(provider)
        brief = _make_brief()

        storyboard = await service.generate_storyboard(script, brief)

        assert [s.number for s in storyboard.scenes] == [1, 2]
        assert storyboard.scenes[0].visual_prompt == "Enriched visual for scene 1"
        assert storyboard.scenes[1].visual_prompt == "Enriched visual for scene 2"


class TestStoryboardServiceBriefConsistency:
    @pytest.mark.asyncio
    async def test_mismatched_brief_id_rejected(self):
        script = _make_script(brief_id=uuid4())  # deliberately unrelated brief
        provider = FakeProvider(text=_valid_storyboard_json(script))
        service = StoryboardService(provider)
        brief = _make_brief()

        with pytest.raises(StoryboardServiceError, match="belongs to brief"):
            await service.generate_storyboard(script, brief)

    @pytest.mark.asyncio
    async def test_mismatched_brief_id_does_not_call_provider(self):
        script = _make_script(brief_id=uuid4())
        provider = FakeProvider(text=_valid_storyboard_json(script))
        service = StoryboardService(provider)
        brief = _make_brief()

        with pytest.raises(StoryboardServiceError):
            await service.generate_storyboard(script, brief)

        assert provider.call_count == 0

    @pytest.mark.asyncio
    async def test_matching_brief_id_accepted(self):
        script = _make_script(brief_id=_DEFAULT_BRIEF_ID)
        provider = FakeProvider(text=_valid_storyboard_json(script))
        service = StoryboardService(provider)
        brief = _make_brief(id=_DEFAULT_BRIEF_ID)

        storyboard = await service.generate_storyboard(script, brief)

        assert isinstance(storyboard, Storyboard)


class TestStoryboardServiceParsing:
    @pytest.mark.asyncio
    async def test_malformed_json(self):
        provider = FakeProvider(text="not json at all")
        service = StoryboardService(provider)

        with pytest.raises(StoryboardServiceError, match="Failed to parse storyboard JSON"):
            await service.generate_storyboard(_make_script(), _make_brief())

    @pytest.mark.asyncio
    async def test_non_dict_response(self):
        provider = FakeProvider(text=json.dumps(["not", "a", "dict"]))
        service = StoryboardService(provider)

        with pytest.raises(StoryboardServiceError, match="must be a JSON object"):
            await service.generate_storyboard(_make_script(), _make_brief())

    @pytest.mark.asyncio
    async def test_missing_scenes_key(self):
        provider = FakeProvider(text=json.dumps({"other": "data"}))
        service = StoryboardService(provider)

        with pytest.raises(StoryboardServiceError, match="missing 'scenes' key"):
            await service.generate_storyboard(_make_script(), _make_brief())

    @pytest.mark.asyncio
    async def test_scenes_not_a_list(self):
        provider = FakeProvider(text=json.dumps({"scenes": "not-an-array"}))
        service = StoryboardService(provider)

        with pytest.raises(StoryboardServiceError, match="'scenes' must be an array"):
            await service.generate_storyboard(_make_script(), _make_brief())


class TestStoryboardServiceSceneEntryValidation:
    @pytest.mark.asyncio
    async def test_non_dict_scene_entry(self):
        provider = FakeProvider(text=json.dumps({"scenes": ["not-a-dict"]}))
        service = StoryboardService(provider)

        with pytest.raises(StoryboardServiceError, match="is not a dict"):
            await service.generate_storyboard(_make_script(), _make_brief())

    @pytest.mark.asyncio
    async def test_missing_number_field(self):
        provider = FakeProvider(
            text=json.dumps({"scenes": [{"visual_prompt": "no number here"}]})
        )
        service = StoryboardService(provider)

        with pytest.raises(StoryboardServiceError, match="invalid 'number'"):
            await service.generate_storyboard(_make_script(), _make_brief())

    @pytest.mark.asyncio
    async def test_non_integer_number_rejected(self):
        provider = FakeProvider(
            text=json.dumps({"scenes": [{"number": "one", "visual_prompt": "x"}]})
        )
        service = StoryboardService(provider)

        with pytest.raises(StoryboardServiceError, match="invalid 'number'"):
            await service.generate_storyboard(_make_script(), _make_brief())

    @pytest.mark.asyncio
    async def test_boolean_number_rejected(self):
        """bool is a subclass of int in Python; True/False must not pass as a number."""
        provider = FakeProvider(
            text=json.dumps({"scenes": [{"number": True, "visual_prompt": "x"}]})
        )
        service = StoryboardService(provider)

        with pytest.raises(StoryboardServiceError, match="invalid 'number'"):
            await service.generate_storyboard(_make_script(), _make_brief())

    @pytest.mark.asyncio
    async def test_duplicate_scene_number_rejected(self):
        script = _make_script(
            scenes=[_make_scene(number=1, narration="only scene", visual_prompt="p")]
        )
        provider = FakeProvider(
            text=json.dumps(
                {
                    "scenes": [
                        {"number": 1, "visual_prompt": "first"},
                        {"number": 1, "visual_prompt": "duplicate"},
                    ]
                }
            )
        )
        service = StoryboardService(provider)
        brief = _make_brief()

        with pytest.raises(StoryboardServiceError, match="Duplicate visual_prompt"):
            await service.generate_storyboard(script, brief)

    @pytest.mark.asyncio
    async def test_missing_scene_coverage_rejected(self):
        script = _make_script()  # scenes 1, 2
        provider = FakeProvider(
            text=json.dumps({"scenes": [{"number": 1, "visual_prompt": "only scene 1"}]})
        )
        service = StoryboardService(provider)
        brief = _make_brief()

        with pytest.raises(StoryboardServiceError, match=r"missing visual_prompt.*\[2\]"):
            await service.generate_storyboard(script, brief)

    @pytest.mark.asyncio
    async def test_extra_unknown_scene_number_rejected(self):
        script = _make_script()  # scenes 1, 2
        provider = FakeProvider(
            text=json.dumps(
                {
                    "scenes": [
                        {"number": 1, "visual_prompt": "scene 1"},
                        {"number": 2, "visual_prompt": "scene 2"},
                        {"number": 3, "visual_prompt": "phantom scene"},
                    ]
                }
            )
        )
        service = StoryboardService(provider)
        brief = _make_brief()

        with pytest.raises(StoryboardServiceError, match=r"unknown scene number.*\[3\]"):
            await service.generate_storyboard(script, brief)

    @pytest.mark.asyncio
    async def test_empty_visual_prompt_rejected(self):
        script = _make_script(
            scenes=[_make_scene(number=1, narration="only scene", visual_prompt="p")]
        )
        provider = FakeProvider(text=json.dumps({"scenes": [{"number": 1, "visual_prompt": ""}]}))
        service = StoryboardService(provider)
        brief = _make_brief()

        with pytest.raises(StoryboardServiceError, match="visual_prompt is empty"):
            await service.generate_storyboard(script, brief)

    @pytest.mark.asyncio
    async def test_non_string_visual_prompt_rejected(self):
        script = _make_script(
            scenes=[_make_scene(number=1, narration="only scene", visual_prompt="p")]
        )
        provider = FakeProvider(
            text=json.dumps({"scenes": [{"number": 1, "visual_prompt": 123}]})
        )
        service = StoryboardService(provider)
        brief = _make_brief()

        with pytest.raises(StoryboardServiceError, match="visual_prompt must be a string"):
            await service.generate_storyboard(script, brief)


class TestStoryboardServiceProviderErrors:
    @pytest.mark.asyncio
    async def test_provider_configuration_error(self):
        from content_engine.providers.exceptions import ProviderConfigurationError

        provider = FakeProvider(
            exc=ProviderConfigurationError(message="Missing API key", provider="gemini")
        )
        service = StoryboardService(provider)

        with pytest.raises(StoryboardServiceError, match="Storyboard generation failed"):
            await service.generate_storyboard(_make_script(), _make_brief())

    @pytest.mark.asyncio
    async def test_provider_quota_error(self):
        from content_engine.providers.exceptions import ProviderQuotaError

        provider = FakeProvider(
            exc=ProviderQuotaError(message="Rate limit exceeded", provider="gemini")
        )
        service = StoryboardService(provider)

        with pytest.raises(StoryboardServiceError, match="Storyboard generation failed"):
            await service.generate_storyboard(_make_script(), _make_brief())

    @pytest.mark.asyncio
    async def test_provider_api_error(self):
        from content_engine.providers.exceptions import ProviderAPIError

        provider = FakeProvider(
            exc=ProviderAPIError(message="Internal server error", provider="gemini")
        )
        service = StoryboardService(provider)

        with pytest.raises(StoryboardServiceError, match="Storyboard generation failed"):
            await service.generate_storyboard(_make_script(), _make_brief())

    @pytest.mark.asyncio
    async def test_provider_generic_error(self):
        provider = FakeProvider(exc=RuntimeError("Unexpected failure"))
        service = StoryboardService(provider)

        with pytest.raises(StoryboardServiceError, match="Storyboard generation failed"):
            await service.generate_storyboard(_make_script(), _make_brief())


class TestStoryboardServiceEdgeCases:
    @pytest.mark.asyncio
    async def test_single_scene_script(self):
        script = _make_script(
            scenes=[_make_scene(number=1, narration="only scene", visual_prompt="p")]
        )
        provider = FakeProvider(text=_valid_storyboard_json(script))
        service = StoryboardService(provider)
        brief = _make_brief()

        storyboard = await service.generate_storyboard(script, brief)

        assert len(storyboard.scenes) == 1
        assert storyboard.scenes[0].number == 1
