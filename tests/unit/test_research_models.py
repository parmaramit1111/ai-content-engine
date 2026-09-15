"""Unit tests for research domain models and enums.

Covers:
- ResearchVerificationStatus: enum values and membership
- ResearchNotes: valid creation, required fields, topic_id association,
  verification status default, optional metadata defaults, timestamps, JSON round-trip,
  invalid enum rejection, and Topic.source_refs preservation
"""

from datetime import UTC
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from content_engine.domain.enums import ResearchVerificationStatus
from content_engine.domain.models import ResearchNotes, Topic

# --- Enum tests ---


class TestResearchVerificationStatus:
    def test_values_match_prd(self):
        assert ResearchVerificationStatus.UNVERIFIED == "unverified"
        assert ResearchVerificationStatus.VERIFIED == "verified"
        assert ResearchVerificationStatus.REJECTED == "rejected"

    def test_has_exactly_three_values(self):
        values = {s.value for s in ResearchVerificationStatus}
        assert values == {"unverified", "verified", "rejected"}

    def test_invalid_value_rejected(self):
        with pytest.raises(ValueError):
            ResearchVerificationStatus("approved")


# --- ResearchNotes model tests ---


class TestResearchNotesCreation:
    def _make_research(self, **overrides) -> ResearchNotes:
        defaults: dict = {
            "topic_id": uuid4(),
            "key_facts": ["RAG reduces hallucinations by grounding responses"],
            "terminology": ["RAG: Retrieval-Augmented Generation"],
            "examples": ["A chatbot fetching docs before answering"],
            "caveats": ["RAG effectiveness depends on retriever quality"],
            "primary_sources": ["https://example.com/rag-paper"],
            "visual_concepts": ["robot thinking with document database"],
        }
        defaults.update(overrides)
        return ResearchNotes(**defaults)

    def test_valid_creation(self):
        research = self._make_research()
        assert isinstance(research, ResearchNotes)
        assert isinstance(research.id, UUID)
        assert isinstance(research.topic_id, UUID)
        assert len(research.key_facts) == 1

    def test_id_auto_generated(self):
        r1 = self._make_research()
        r2 = self._make_research()
        assert r1.id != r2.id

    def test_verification_status_defaults_to_unverified(self):
        research = ResearchNotes(topic_id=uuid4())
        assert research.verification_status == ResearchVerificationStatus.UNVERIFIED

    def test_optional_metadata_defaults_to_none(self):
        research = ResearchNotes(topic_id=uuid4())
        assert research.notebooklm_session is None
        assert research.source_notes is None
        assert research.confidence_scores is None
        assert research.annotations is None

    def test_optional_metadata_accepted(self):
        research = self._make_research(
            notebooklm_session="session-123",
            source_notes="Used sources A and B",
            confidence_scores={"fact-1": 0.9},
            annotations="Checked by Alice",
        )
        assert research.notebooklm_session == "session-123"
        assert research.source_notes == "Used sources A and B"
        assert research.confidence_scores == {"fact-1": 0.9}
        assert research.annotations == "Checked by Alice"

    def test_timestamps_are_utc_aware(self):
        research = self._make_research()
        assert research.created_at.tzinfo == UTC
        assert research.updated_at.tzinfo == UTC


class TestResearchNotesValidation:
    def test_missing_topic_id_raises(self):
        with pytest.raises(ValidationError, match="Field required"):
            ResearchNotes(
                key_facts=["fact"],
                terminology=["term"],
                examples=["ex"],
                caveats=["caveat"],
                primary_sources=["src"],
                visual_concepts=["vc"],
            )

    def test_invalid_verification_status_raises(self):
        with pytest.raises(ValidationError):
            ResearchNotes(
                topic_id=uuid4(),
                verification_status="invalid_status",
            )

    def test_empty_lists_allowed(self):
        research = ResearchNotes(topic_id=uuid4())
        assert research.key_facts == []
        assert research.terminology == []
        assert research.examples == []
        assert research.caveats == []
        assert research.primary_sources == []
        assert research.visual_concepts == []

    def test_lists_can_hold_arbitrary_strings(self):
        research = ResearchNotes(
            topic_id=uuid4(),
            key_facts=["fact one", "fact two", "fact three"],
            terminology=["term: definition"],
            examples=["ex1", "ex2"],
            caveats=["caveat1"],
            primary_sources=["https://a.com", "https://b.com"],
            visual_concepts=["wide shot", "close-up"],
        )
        assert len(research.key_facts) == 3
        assert len(research.primary_sources) == 2


# --- Topic.source_refs preservation tests ---


class TestTopicSourceRefsPreservation:
    def test_topic_source_refs_unchanged_by_research(self):
        """ResearchNotes must not duplicate or alter Topic.source_refs."""
        topic = Topic(
            title="What is RAG?",
            category="ai_engineering",
            audience="developers",
            difficulty="beginner",
            hook="Ever wonder how LLMs know your docs?",
        )
        topic.source_refs.extend(["https://docs.example.com", "https://arxiv.org/123"])

        research = ResearchNotes(
            topic_id=topic.id,
            key_facts=["RAG groundss responses"],
            terminology=["RAG"],
            examples=["chatbot"],
            caveats=["retriever quality matters"],
            primary_sources=["https://arxiv.org/123"],
            visual_concepts=["database diagram"],
        )

        assert topic.source_refs == ["https://docs.example.com", "https://arxiv.org/123"]
        assert research.topic_id == topic.id
        assert research.primary_sources == ["https://arxiv.org/123"]
        assert research.primary_sources is not topic.source_refs

    def test_topic_can_be_reconstructed_after_research(self):
        """Topic.source_refs round-trips correctly — research does not corrupt it."""
        topic = Topic(
            title="Test",
            category="backend_engineering",
            audience="backend engineers",
            difficulty="advanced",
            hook="Why is this slow?",
            source_refs=["https://perf.example.com"],
        )
        stored_refs = list(topic.source_refs)

        ResearchNotes(
            topic_id=topic.id,
            key_facts=["fact"],
            terminology=["term"],
            examples=["ex"],
            caveats=["caveat"],
            primary_sources=["https://r.example.com"],
            visual_concepts=["vc"],
        )

        assert topic.source_refs == stored_refs


# --- JSON round-trip tests ---


class TestResearchNotesJSON:
    def test_json_round_trip(self):
        research = ResearchNotes(
            topic_id=uuid4(),
            key_facts=["fact"],
            terminology=["term: def"],
            examples=["ex"],
            caveats=["caveat"],
            primary_sources=["https://src.example.com"],
            visual_concepts=["vc"],
            verification_status=ResearchVerificationStatus.VERIFIED,
        )
        data = research.model_dump_json()
        restored = ResearchNotes.model_validate_json(data)
        assert restored.key_facts == ["fact"]
        assert restored.verification_status == ResearchVerificationStatus.VERIFIED
        assert restored.topic_id == research.topic_id
        assert restored.id == research.id
