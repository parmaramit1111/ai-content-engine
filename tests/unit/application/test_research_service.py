"""Unit tests for the ResearchService.

Covers:
1.  valid research creation
2.  minimal required-field creation
3.  topic_id association
4.  verification_status default
5.  is_ready_for_brief: UNVERIFIED returns False
6.  is_ready_for_brief: VERIFIED with facts + sources returns True
7.  is_ready_for_brief: VERIFIED with empty key_facts returns False
8.  is_ready_for_brief: VERIFIED with empty primary_sources returns False
9.  is_ready_for_brief: REJECTED returns False
10. provider independence (no provider imported)

No real external calls; all tests use in-memory construction.
"""

from inspect import getsource
from uuid import UUID, uuid4

from content_engine.application.research_service import ResearchService
from content_engine.domain.enums import ResearchVerificationStatus
from content_engine.domain.models import ResearchNotes, Topic


def _topic() -> Topic:
    return Topic(
        title="What is RAG?",
        category="ai_engineering",
        audience="developers",
        difficulty="beginner",
        hook="Ever wonder how LLMs know your docs?",
    )


class TestResearchServiceCreate:
    def test_create_research_returns_validated_model(self):
        svc = ResearchService()
        topic = _topic()
        research = svc.create_research(
            topic_id=topic.id,
            key_facts=["RAG grounds LLM responses"],
            terminology=["RAG: Retrieval-Augmented Generation"],
            examples=["A chatbot fetching docs before answering"],
            caveats=["Effectiveness depends on retriever quality"],
            primary_sources=["https://arxiv.org/abs/1706.01618"],
            visual_concepts=["Database connecting to LLM"],
        )
        assert isinstance(research, ResearchNotes)
        assert research.id is not None
        assert research.topic_id == topic.id

    def test_create_research_minimal_required_fields(self):
        svc = ResearchService()
        topic = _topic()
        research = svc.create_research(
            topic_id=topic.id,
            key_facts=["fact"],
            terminology=["term"],
            examples=["ex"],
            caveats=["caveat"],
            primary_sources=["https://example.com"],
            visual_concepts=["vc"],
        )
        assert research.verification_status == ResearchVerificationStatus.UNVERIFIED
        assert research.notebooklm_session is None

    def test_create_research_with_optional_metadata(self):
        svc = ResearchService()
        research = svc.create_research(
            topic_id=uuid4(),
            key_facts=["fact"],
            terminology=["term"],
            examples=["ex"],
            caveats=["caveat"],
            primary_sources=["src"],
            visual_concepts=["vc"],
            verification_status=ResearchVerificationStatus.VERIFIED,
            notebooklm_session="notebook-123",
            source_notes="Used sources A and B in NotebookLM",
            confidence_scores={"fact": 0.95},
            annotations="Reviewed by Alice",
        )
        assert research.verification_status == ResearchVerificationStatus.VERIFIED
        assert research.notebooklm_session == "notebook-123"
        assert research.source_notes == "Used sources A and B in NotebookLM"
        assert research.confidence_scores == {"fact": 0.95}
        assert research.annotations == "Reviewed by Alice"

    def test_create_research_topic_id_association(self):
        svc = ResearchService()
        topic_id = uuid4()
        research = svc.create_research(
            topic_id=topic_id,
            key_facts=["fact"],
            terminology=["term"],
            examples=["ex"],
            caveats=["caveat"],
            primary_sources=["src"],
            visual_concepts=["vc"],
        )
        assert isinstance(research.topic_id, UUID)
        assert research.topic_id == topic_id

    def test_create_research_is_provider_agnostic(self):
        """ResearchService must not import or depend on any provider implementation."""
        source = getsource(ResearchService)
        assert "gemini" not in source.lower()
        assert "google.genai" not in source
        assert "GeminiProvider" not in source


class TestResearchServiceIsReadyForBrief:
    def test_unverified_returns_false(self):
        svc = ResearchService()
        research = svc.create_research(
            topic_id=uuid4(),
            key_facts=["fact"],
            terminology=["term"],
            examples=["ex"],
            caveats=["caveat"],
            primary_sources=["src"],
            visual_concepts=["vc"],
            verification_status=ResearchVerificationStatus.UNVERIFIED,
        )
        assert svc.is_ready_for_brief(research) is False

    def test_verified_with_facts_and_sources_returns_true(self):
        svc = ResearchService()
        research = svc.create_research(
            topic_id=uuid4(),
            key_facts=["fact"],
            terminology=["term"],
            examples=["ex"],
            caveats=["caveat"],
            primary_sources=["https://src.example.com"],
            visual_concepts=["vc"],
            verification_status=ResearchVerificationStatus.VERIFIED,
        )
        assert svc.is_ready_for_brief(research) is True

    def test_verified_empty_key_facts_returns_false(self):
        svc = ResearchService()
        research = ResearchNotes(
            topic_id=uuid4(),
            verification_status=ResearchVerificationStatus.VERIFIED,
            primary_sources=["https://src.example.com"],
        )
        assert svc.is_ready_for_brief(research) is False

    def test_verified_empty_primary_sources_returns_false(self):
        svc = ResearchService()
        research = ResearchNotes(
            topic_id=uuid4(),
            key_facts=["fact"],
            verification_status=ResearchVerificationStatus.VERIFIED,
        )
        assert svc.is_ready_for_brief(research) is False

    def test_rejected_returns_false(self):
        svc = ResearchService()
        research = svc.create_research(
            topic_id=uuid4(),
            key_facts=["fact"],
            terminology=["term"],
            examples=["ex"],
            caveats=["caveat"],
            primary_sources=["src"],
            visual_concepts=["vc"],
            verification_status=ResearchVerificationStatus.REJECTED,
        )
        assert svc.is_ready_for_brief(research) is False
