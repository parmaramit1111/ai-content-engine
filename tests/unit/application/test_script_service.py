"""Focused unit tests for the ScriptService vertical slice.

Tests cover:
1.  valid generation request
2.  invalid request validation
3.  deterministic prompt construction
4.  provider invocation
5.  provider independence using a fake provider
6.  successful generation
7.  valid JSON parsing
8.  malformed JSON
9.  missing required fields
10. invalid scene data
11. provider configuration error
12. provider quota/budget error
13. provider API error
14. resulting Script validation

No real Gemini API calls. Uses a fake TextGenerationProvider.
"""

import json
from typing import Any

import pytest

from content_engine.application.script_service import (
    ScriptService,
    ScriptServiceError,
)
from content_engine.domain.models import ContentBrief, Scene, Script
from content_engine.providers.results import GenerationResult


class FakeProvider:
    """Test double implementing TextGenerationProvider.

    Returns a configurable GenerationResult or raises an exception.
    Verifies the service does not import or depend on GeminiProvider.
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


def _make_brief(**overrides: Any) -> ContentBrief:
    defaults = {
        "topic": "What is RAG?",
        "problem": "LLMs hallucinate without context",
        "core_explanation": "RAG combines retrieval with generation",
        "example": "A chatbot fetching docs before answering",
        "takeaway": "RAG reduces hallucinations by grounding responses",
        "cta": "Try RAG in your next project",
        "estimated_duration": 45,
        "visual_style": "Clean diagrams, dark theme, 9:16 vertical",
    }
    defaults.update(overrides)
    return ContentBrief(**defaults)


def _valid_script_json() -> str:
    return json.dumps(
        {
            "scenes": [
                {
                    "number": 1,
                    "duration": 5.0,
                    "narration": "Hook: Ever wonder how LLMs know your docs?",
                    "visual_prompt": "Wide shot of a robot thinking",
                    "onscreen_text": "RAG",
                    "transition": "cut",
                },
                {
                    "number": 2,
                    "duration": 40.0,
                    "narration": "RAG combines retrieval with generation to reduce hallucinations.",
                    "visual_prompt": "Close-up of database diagram",
                },
            ],
        }
    )


class TestScriptServiceInit:
    def test_service_stores_provider(self):
        provider = FakeProvider(text="{}")
        service = ScriptService(provider)
        assert service._provider is provider


class TestScriptServiceGenerateScript:
    @pytest.mark.asyncio
    async def test_valid_generation_request(self):
        provider = FakeProvider(text=_valid_script_json())
        service = ScriptService(provider)
        brief = _make_brief()

        script = await service.generate_script(brief)

        assert isinstance(script, Script)
        assert script.brief_id == brief.id
        assert script.version == 1
        assert len(script.scenes) == 2

    @pytest.mark.asyncio
    async def test_provider_invocation(self):
        provider = FakeProvider(text=_valid_script_json())
        service = ScriptService(provider)
        brief = _make_brief()

        await service.generate_script(brief)

        assert provider.call_count == 1
        assert provider.last_operation == "script"
        assert provider.last_content_id == str(brief.id)

    @pytest.mark.asyncio
    async def test_provider_independence_with_fake_provider(self):
        """Service must work with any TextGenerationProvider, not just Gemini."""
        provider = FakeProvider(text=_valid_script_json())
        service = ScriptService(provider)
        brief = _make_brief()

        script = await service.generate_script(brief)

        assert script.scenes[0].narration == "Hook: Ever wonder how LLMs know your docs?"
        assert script.scenes[1].duration == 40.0

    @pytest.mark.asyncio
    async def test_deterministic_prompt_construction(self):
        provider = FakeProvider(text=_valid_script_json())
        service = ScriptService(provider)
        brief = _make_brief()

        await service.generate_script(brief)

        prompt = provider.last_prompt
        assert brief.topic in prompt
        assert brief.problem in prompt
        assert brief.core_explanation in prompt
        assert brief.example in prompt
        assert brief.takeaway in prompt
        assert brief.cta in prompt
        assert str(brief.estimated_duration) in prompt
        assert brief.visual_style in prompt
        assert "scenes" in prompt.lower()

    @pytest.mark.asyncio
    async def test_custom_version_number(self):
        provider = FakeProvider(text=_valid_script_json())
        service = ScriptService(provider)
        brief = _make_brief()

        script = await service.generate_script(brief, version=3)
        assert script.version == 3


class TestScriptServiceParsing:
    @pytest.mark.asyncio
    async def test_valid_json_parsing(self):
        provider = FakeProvider(text=_valid_script_json())
        service = ScriptService(provider)
        brief = _make_brief()

        script = await service.generate_script(brief)

        scene1 = script.scenes[0]
        assert scene1.number == 1
        assert scene1.duration == 5.0
        assert scene1.onscreen_text == "RAG"
        assert scene1.transition == "cut"

    @pytest.mark.asyncio
    async def test_malformed_json(self):
        provider = FakeProvider(text="not json at all")
        service = ScriptService(provider)
        brief = _make_brief()

        with pytest.raises(ScriptServiceError, match="Failed to parse script JSON"):
            await service.generate_script(brief)

    @pytest.mark.asyncio
    async def test_missing_scenes_key(self):
        provider = FakeProvider(text=json.dumps({"other": "data"}))
        service = ScriptService(provider)
        brief = _make_brief()

        with pytest.raises(ScriptServiceError, match="missing 'scenes' key"):
            await service.generate_script(brief)

    @pytest.mark.asyncio
    async def test_scenes_not_array(self):
        provider = FakeProvider(text=json.dumps({"scenes": "not-an-array"}))
        service = ScriptService(provider)
        brief = _make_brief()

        with pytest.raises(ScriptServiceError, match="'scenes' must be an array"):
            await service.generate_script(brief)

    @pytest.mark.asyncio
    async def test_empty_scenes_list(self):
        provider = FakeProvider(text=json.dumps({"scenes": []}))
        service = ScriptService(provider)
        brief = _make_brief()

        with pytest.raises(ScriptServiceError, match="empty scenes list"):
            await service.generate_script(brief)


class TestScriptServiceSceneValidation:
    @pytest.mark.asyncio
    async def test_missing_required_field(self):
        provider = FakeProvider(
            text=json.dumps(
                {
                    "scenes": [
                        {"number": 1, "duration": 5.0}  # missing narration, visual_prompt
                    ]
                }
            )
        )
        service = ScriptService(provider)
        brief = _make_brief()

        with pytest.raises(ScriptServiceError, match="missing"):
            await service.generate_script(brief)

    @pytest.mark.asyncio
    async def test_invalid_scene_number(self):
        provider = FakeProvider(
            text=json.dumps(
                {
                    "scenes": [
                        {
                            "number": 5,
                            "duration": 5.0,
                            "narration": "test",
                            "visual_prompt": "visual",
                        }
                    ]
                }
            )
        )
        service = ScriptService(provider)
        brief = _make_brief()

        with pytest.raises(ScriptServiceError, match="expected 1"):
            await service.generate_script(brief)

    @pytest.mark.asyncio
    async def test_non_sequential_scene_numbers(self):
        provider = FakeProvider(
            text=json.dumps(
                {
                    "scenes": [
                        {
                            "number": 1,
                            "duration": 5.0,
                            "narration": "first",
                            "visual_prompt": "visual",
                        },
                        {
                            "number": 3,
                            "duration": 5.0,
                            "narration": "second",
                            "visual_prompt": "visual",
                        },
                    ]
                }
            )
        )
        service = ScriptService(provider)
        brief = _make_brief()

        with pytest.raises(ScriptServiceError, match="expected 2"):
            await service.generate_script(brief)

    @pytest.mark.asyncio
    async def test_non_numeric_duration(self):
        provider = FakeProvider(
            text=json.dumps(
                {
                    "scenes": [
                        {
                            "number": 1,
                            "duration": "not-a-number",
                            "narration": "test",
                            "visual_prompt": "visual",
                        }
                    ]
                }
            )
        )
        service = ScriptService(provider)
        brief = _make_brief()

        with pytest.raises(ScriptServiceError, match="must be a number"):
            await service.generate_script(brief)

    @pytest.mark.asyncio
    async def test_negative_duration(self):
        provider = FakeProvider(
            text=json.dumps(
                {
                    "scenes": [
                        {
                            "number": 1,
                            "duration": -5.0,
                            "narration": "test",
                            "visual_prompt": "visual",
                        }
                    ]
                }
            )
        )
        service = ScriptService(provider)
        brief = _make_brief()

        with pytest.raises(ScriptServiceError, match="non-negative"):
            await service.generate_script(brief)

    @pytest.mark.asyncio
    async def test_empty_narration_rejected(self):
        provider = FakeProvider(
            text=json.dumps(
                {
                    "scenes": [
                        {
                            "number": 1,
                            "duration": 5.0,
                            "narration": "",
                            "visual_prompt": "visual",
                        }
                    ]
                }
            )
        )
        service = ScriptService(provider)
        brief = _make_brief()

        with pytest.raises(ScriptServiceError, match="empty"):
            await service.generate_script(brief)

    @pytest.mark.asyncio
    async def test_non_dict_scene(self):
        provider = FakeProvider(text=json.dumps({"scenes": ["not-a-dict"]}))
        service = ScriptService(provider)
        brief = _make_brief()

        with pytest.raises(ScriptServiceError, match="is not a dict"):
            await service.generate_script(brief)


class TestScriptServiceProviderErrors:
    @pytest.mark.asyncio
    async def test_provider_configuration_error(self):
        from content_engine.providers.exceptions import ProviderConfigurationError

        provider = FakeProvider(
            exc=ProviderConfigurationError(message="Missing API key", provider="gemini")
        )
        service = ScriptService(provider)
        brief = _make_brief()

        with pytest.raises(ScriptServiceError, match="Script generation failed"):
            await service.generate_script(brief)

    @pytest.mark.asyncio
    async def test_provider_quota_error(self):
        from content_engine.providers.exceptions import ProviderQuotaError

        provider = FakeProvider(
            exc=ProviderQuotaError(message="Rate limit exceeded", provider="gemini")
        )
        service = ScriptService(provider)
        brief = _make_brief()

        with pytest.raises(ScriptServiceError, match="Script generation failed"):
            await service.generate_script(brief)

    @pytest.mark.asyncio
    async def test_provider_api_error(self):
        from content_engine.providers.exceptions import ProviderAPIError

        provider = FakeProvider(
            exc=ProviderAPIError(message="Internal server error", provider="gemini")
        )
        service = ScriptService(provider)
        brief = _make_brief()

        with pytest.raises(ScriptServiceError, match="Script generation failed"):
            await service.generate_script(brief)

    @pytest.mark.asyncio
    async def test_provider_generic_error(self):
        provider = FakeProvider(exc=RuntimeError("Unexpected failure"))
        service = ScriptService(provider)
        brief = _make_brief()

        with pytest.raises(ScriptServiceError, match="Script generation failed"):
            await service.generate_script(brief)


class TestScriptServiceResultValidation:
    @pytest.mark.asyncio
    async def test_resulting_script_has_valid_scenes(self):
        provider = FakeProvider(text=_valid_script_json())
        service = ScriptService(provider)
        brief = _make_brief()

        script = await service.generate_script(brief)

        assert isinstance(script, Script)
        assert script.brief_id == brief.id
        assert all(isinstance(s, Scene) for s in script.scenes)
        assert all(s.number >= 1 for s in script.scenes)
        assert all(s.duration >= 0 for s in script.scenes)
        assert all(len(s.narration) >= 1 for s in script.scenes)
        assert all(len(s.visual_prompt) >= 1 for s in script.scenes)

    @pytest.mark.asyncio
    async def test_scene_sequence_is_sequential(self):
        provider = FakeProvider(text=_valid_script_json())
        service = ScriptService(provider)
        brief = _make_brief()

        script = await service.generate_script(brief)

        numbers = [s.number for s in script.scenes]
        assert numbers == list(range(1, len(numbers) + 1))

    @pytest.mark.asyncio
    async def test_onscreen_text_optional(self):
        json_data = {
            "scenes": [
                {
                    "number": 1,
                    "duration": 5.0,
                    "narration": "Test",
                    "visual_prompt": "Visual",
                }
            ]
        }
        provider = FakeProvider(text=json.dumps(json_data))
        service = ScriptService(provider)
        brief = _make_brief()

        script = await service.generate_script(brief)
        assert script.scenes[0].onscreen_text is None
        assert script.scenes[0].transition is None

    @pytest.mark.asyncio
    async def test_optional_fields_preserved_when_present(self):
        json_data = {
            "scenes": [
                {
                    "number": 1,
                    "duration": 5.0,
                    "narration": "Test",
                    "visual_prompt": "Visual",
                    "onscreen_text": "Hello",
                    "transition": "fade",
                }
            ]
        }
        provider = FakeProvider(text=json.dumps(json_data))
        service = ScriptService(provider)
        brief = _make_brief()

        script = await service.generate_script(brief)
        assert script.scenes[0].onscreen_text == "Hello"
        assert script.scenes[0].transition == "fade"
