"""Focused unit tests for the BriefService vertical slice.

Tests cover:
1.  valid generation request
2.  provider invocation (operation="brief", content_id)
3.  provider independence using a fake provider + no Gemini import
4.  deterministic prompt construction (topic + research grounding)
5.  topic title used verbatim, not requested from the provider
6.  source merging from Topic.source_refs + ResearchNotes.primary_sources
7.  provider-supplied "sources" are ignored (hallucination guard)
8.  malformed JSON
9.  non-dict JSON response
10. missing required fields
11. invalid/empty field values
12. invalid estimated_duration (type, range, bool rejection, fractional rejection,
    whole-number float normalization)
13. provider configuration/quota/API/generic errors
14. research.topic_id must match topic.id

No real Gemini API calls. Uses a fake TextGenerationProvider.
"""

import ast
import json
from inspect import getsource
from typing import Any
from uuid import uuid4

import pytest

from content_engine.application import brief_service as brief_service_module
from content_engine.application.brief_service import BriefService, BriefServiceError
from content_engine.domain.models import ContentBrief, ResearchNotes, Topic
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


# Shared default so independently-built _make_topic()/_make_research() calls
# are linked by default; tests that need a mismatch pass an explicit topic_id.
_DEFAULT_TOPIC_ID = uuid4()


def _make_topic(**overrides: Any) -> Topic:
    defaults = {
        "id": _DEFAULT_TOPIC_ID,
        "title": "What is RAG?",
        "category": "ai_engineering",
        "audience": "backend developers",
        "difficulty": "beginner",
        "hook": "Ever wonder how LLMs know your docs?",
        "source_refs": ["https://docs.example.com/rag"],
    }
    defaults.update(overrides)
    return Topic(**defaults)


def _make_research(**overrides: Any) -> ResearchNotes:
    defaults: dict[str, Any] = {
        "topic_id": _DEFAULT_TOPIC_ID,
        "key_facts": ["RAG grounds LLM responses in retrieved documents"],
        "terminology": ["RAG: Retrieval-Augmented Generation"],
        "examples": ["A chatbot fetching docs before answering"],
        "caveats": ["Effectiveness depends on retriever quality"],
        "primary_sources": ["https://arxiv.org/abs/1706.01618"],
        "visual_concepts": ["Database connecting to an LLM"],
    }
    defaults.update(overrides)
    return ResearchNotes(**defaults)


def _valid_brief_json(**overrides: Any) -> str:
    defaults = {
        "problem": "LLMs hallucinate without grounded context",
        "core_explanation": "RAG combines retrieval with generation",
        "example": "A chatbot fetching docs before answering",
        "takeaway": "RAG reduces hallucinations by grounding responses",
        "cta": "Try RAG in your next project",
        "estimated_duration": 45,
        "visual_style": "Clean diagrams, dark theme, 9:16 vertical",
    }
    defaults.update(overrides)
    return json.dumps(defaults)


class TestBriefServiceInit:
    def test_service_stores_provider(self):
        provider = FakeProvider(text="{}")
        service = BriefService(provider)
        assert service._provider is provider


class TestBriefServiceGenerateBrief:
    @pytest.mark.asyncio
    async def test_valid_generation_request(self):
        provider = FakeProvider(text=_valid_brief_json())
        service = BriefService(provider)
        topic = _make_topic()
        research = _make_research()

        brief = await service.generate_brief(topic, research)

        assert isinstance(brief, ContentBrief)
        assert brief.topic == topic.title
        assert brief.problem == "LLMs hallucinate without grounded context"
        assert brief.estimated_duration == 45

    @pytest.mark.asyncio
    async def test_provider_invocation(self):
        provider = FakeProvider(text=_valid_brief_json())
        service = BriefService(provider)
        topic = _make_topic()
        research = _make_research()

        await service.generate_brief(topic, research)

        assert provider.call_count == 1
        assert provider.last_operation == "brief"
        assert provider.last_content_id == str(topic.id)

    @pytest.mark.asyncio
    async def test_provider_independence_with_fake_provider(self):
        """Service must work with any TextGenerationProvider, not just Gemini."""
        provider = FakeProvider(text=_valid_brief_json())
        service = BriefService(provider)
        topic = _make_topic()
        research = _make_research()

        brief = await service.generate_brief(topic, research)

        assert brief.cta == "Try RAG in your next project"

    def test_brief_service_is_provider_agnostic(self):
        """No import anywhere in the brief_service module may reference a
        concrete provider (e.g. Gemini/google.genai).

        Scans the module's actual `import`/`from ... import` statements via
        `ast`, not just the class body — `inspect.getsource(BriefService)`
        alone would miss a provider-specific import added at module scope,
        since imports live above the class definition. A plain substring
        scan of the whole module source is not used either, because the
        module's own docstrings legitimately mention "Gemini" when
        explaining what the service must NOT depend on.
        """
        tree = ast.parse(getsource(brief_service_module))
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

    @pytest.mark.asyncio
    async def test_deterministic_prompt_construction(self):
        provider = FakeProvider(text=_valid_brief_json())
        service = BriefService(provider)
        topic = _make_topic()
        research = _make_research()

        await service.generate_brief(topic, research)

        prompt = provider.last_prompt
        assert topic.title in prompt
        assert topic.audience in prompt
        assert topic.hook in prompt
        assert research.key_facts[0] in prompt
        assert research.terminology[0] in prompt
        assert research.caveats[0] in prompt
        assert "json" in prompt.lower()

    @pytest.mark.asyncio
    async def test_topic_title_used_verbatim_not_from_provider(self):
        provider = FakeProvider(text=_valid_brief_json(problem="ignored placeholder"))
        service = BriefService(provider)
        topic = _make_topic(title="Exact Title From Topic")
        research = _make_research()

        brief = await service.generate_brief(topic, research)

        assert brief.topic == "Exact Title From Topic"


class TestBriefServiceTopicResearchConsistency:
    @pytest.mark.asyncio
    async def test_mismatched_research_topic_id_rejected(self):
        provider = FakeProvider(text=_valid_brief_json())
        service = BriefService(provider)
        topic = _make_topic()
        research = _make_research(topic_id=uuid4())  # deliberately unrelated topic

        with pytest.raises(BriefServiceError, match="belongs to topic"):
            await service.generate_brief(topic, research)

    @pytest.mark.asyncio
    async def test_mismatched_research_topic_id_does_not_call_provider(self):
        """The check must happen before any provider call is made."""
        provider = FakeProvider(text=_valid_brief_json())
        service = BriefService(provider)
        topic = _make_topic()
        research = _make_research(topic_id=uuid4())

        with pytest.raises(BriefServiceError):
            await service.generate_brief(topic, research)

        assert provider.call_count == 0

    @pytest.mark.asyncio
    async def test_matching_research_topic_id_accepted(self):
        provider = FakeProvider(text=_valid_brief_json())
        service = BriefService(provider)
        topic = _make_topic()
        research = _make_research(topic_id=topic.id)

        brief = await service.generate_brief(topic, research)

        assert isinstance(brief, ContentBrief)


class TestBriefServiceSourceMerging:
    @pytest.mark.asyncio
    async def test_sources_merged_from_topic_and_research(self):
        provider = FakeProvider(text=_valid_brief_json())
        service = BriefService(provider)
        topic = _make_topic(source_refs=["https://docs.example.com/rag"])
        research = _make_research(primary_sources=["https://arxiv.org/abs/1706.01618"])

        brief = await service.generate_brief(topic, research)

        assert brief.sources == [
            "https://docs.example.com/rag",
            "https://arxiv.org/abs/1706.01618",
        ]

    @pytest.mark.asyncio
    async def test_sources_deduplicated_preserving_order(self):
        provider = FakeProvider(text=_valid_brief_json())
        service = BriefService(provider)
        shared = "https://shared.example.com"
        topic = _make_topic(source_refs=[shared])
        research = _make_research(primary_sources=[shared, "https://other.example.com"])

        brief = await service.generate_brief(topic, research)

        assert brief.sources == [shared, "https://other.example.com"]

    @pytest.mark.asyncio
    async def test_provider_supplied_sources_are_ignored(self):
        """Sources must never be taken from provider output, only from inputs."""
        text = json.dumps(
            {
                "problem": "problem",
                "core_explanation": "explanation",
                "example": "example",
                "takeaway": "takeaway",
                "cta": "cta",
                "estimated_duration": 30,
                "visual_style": "style",
                "sources": ["https://hallucinated.example.com"],
            }
        )
        provider = FakeProvider(text=text)
        service = BriefService(provider)
        topic = _make_topic(source_refs=["https://real.example.com"])
        research = _make_research(primary_sources=[])

        brief = await service.generate_brief(topic, research)

        assert brief.sources == ["https://real.example.com"]
        assert "https://hallucinated.example.com" not in brief.sources


class TestBriefServiceParsing:
    @pytest.mark.asyncio
    async def test_malformed_json(self):
        provider = FakeProvider(text="not json at all")
        service = BriefService(provider)

        with pytest.raises(BriefServiceError, match="Failed to parse content brief JSON"):
            await service.generate_brief(_make_topic(), _make_research())

    @pytest.mark.asyncio
    async def test_non_dict_response(self):
        provider = FakeProvider(text=json.dumps(["not", "a", "dict"]))
        service = BriefService(provider)

        with pytest.raises(BriefServiceError, match="must be a JSON object"):
            await service.generate_brief(_make_topic(), _make_research())

    @pytest.mark.asyncio
    async def test_missing_required_fields(self):
        provider = FakeProvider(text=json.dumps({"problem": "only this"}))
        service = BriefService(provider)

        with pytest.raises(BriefServiceError, match="missing required field"):
            await service.generate_brief(_make_topic(), _make_research())


class TestBriefServiceFieldValidation:
    @pytest.mark.asyncio
    async def test_empty_string_field_rejected(self):
        provider = FakeProvider(text=_valid_brief_json(problem=""))
        service = BriefService(provider)

        with pytest.raises(BriefServiceError, match="problem is empty"):
            await service.generate_brief(_make_topic(), _make_research())

    @pytest.mark.asyncio
    async def test_non_string_field_rejected(self):
        provider = FakeProvider(text=_valid_brief_json(cta=123))
        service = BriefService(provider)

        with pytest.raises(BriefServiceError, match="cta must be a string"):
            await service.generate_brief(_make_topic(), _make_research())

    @pytest.mark.asyncio
    async def test_non_integer_duration_rejected(self):
        provider = FakeProvider(text=_valid_brief_json(estimated_duration="soon"))
        service = BriefService(provider)

        with pytest.raises(BriefServiceError, match="estimated_duration must be an integer"):
            await service.generate_brief(_make_topic(), _make_research())

    @pytest.mark.asyncio
    async def test_non_positive_duration_rejected(self):
        provider = FakeProvider(text=_valid_brief_json(estimated_duration=0))
        service = BriefService(provider)

        with pytest.raises(BriefServiceError, match="estimated_duration must be >= 1"):
            await service.generate_brief(_make_topic(), _make_research())

    @pytest.mark.asyncio
    async def test_boolean_duration_rejected(self):
        """bool is a subclass of int in Python; True/False must not pass as a duration."""
        provider = FakeProvider(text=_valid_brief_json(estimated_duration=True))
        service = BriefService(provider)

        with pytest.raises(BriefServiceError, match="estimated_duration must be an integer"):
            await service.generate_brief(_make_topic(), _make_research())

    @pytest.mark.asyncio
    async def test_fractional_duration_rejected(self):
        """A non-whole-number float must be rejected, not silently truncated."""
        provider = FakeProvider(text=_valid_brief_json(estimated_duration=44.9))
        service = BriefService(provider)

        with pytest.raises(
            BriefServiceError, match="estimated_duration must be a whole number of seconds"
        ):
            await service.generate_brief(_make_topic(), _make_research())

    @pytest.mark.asyncio
    async def test_whole_number_float_duration_normalized(self):
        """A whole-number float (e.g. 45.0) is normalized to int, not rejected."""
        provider = FakeProvider(text=_valid_brief_json(estimated_duration=45.0))
        service = BriefService(provider)

        brief = await service.generate_brief(_make_topic(), _make_research())

        assert brief.estimated_duration == 45
        assert isinstance(brief.estimated_duration, int)


class TestBriefServiceProviderErrors:
    @pytest.mark.asyncio
    async def test_provider_configuration_error(self):
        from content_engine.providers.exceptions import ProviderConfigurationError

        provider = FakeProvider(
            exc=ProviderConfigurationError(message="Missing API key", provider="gemini")
        )
        service = BriefService(provider)

        with pytest.raises(BriefServiceError, match="Content brief generation failed"):
            await service.generate_brief(_make_topic(), _make_research())

    @pytest.mark.asyncio
    async def test_provider_quota_error(self):
        from content_engine.providers.exceptions import ProviderQuotaError

        provider = FakeProvider(
            exc=ProviderQuotaError(message="Rate limit exceeded", provider="gemini")
        )
        service = BriefService(provider)

        with pytest.raises(BriefServiceError, match="Content brief generation failed"):
            await service.generate_brief(_make_topic(), _make_research())

    @pytest.mark.asyncio
    async def test_provider_api_error(self):
        from content_engine.providers.exceptions import ProviderAPIError

        provider = FakeProvider(
            exc=ProviderAPIError(message="Internal server error", provider="gemini")
        )
        service = BriefService(provider)

        with pytest.raises(BriefServiceError, match="Content brief generation failed"):
            await service.generate_brief(_make_topic(), _make_research())

    @pytest.mark.asyncio
    async def test_provider_generic_error(self):
        provider = FakeProvider(exc=RuntimeError("Unexpected failure"))
        service = BriefService(provider)

        with pytest.raises(BriefServiceError, match="Content brief generation failed"):
            await service.generate_brief(_make_topic(), _make_research())
