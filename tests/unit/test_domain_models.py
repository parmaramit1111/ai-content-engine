"""Unit tests for domain models and enums."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from content_engine.domain.enums import Category, Difficulty, TopicStatus
from content_engine.domain.models import ContentBrief, Scene, Script, Topic

# --- Enum tests ---


class TestTopicStatus:
    def test_all_statuses_match_prd(self):
        expected = {
            "IDEA",
            "RESEARCHING",
            "SCRIPTED",
            "STORYBOARDED",
            "GENERATING",
            "EDITING",
            "REVIEW",
            "APPROVED",
            "PUBLISHED",
            "ANALYZING",
            "ARCHIVED",
        }
        actual = {s.value for s in TopicStatus}
        assert actual == expected

    def test_default_status_is_idea(self):
        assert TopicStatus.IDEA.value == "IDEA"


class TestCategory:
    def test_categories_match_prd(self):
        expected = {
            "ai_engineering",
            "backend_engineering",
            "architecture",
            "engineering_lessons",
        }
        actual = {c.value for c in Category}
        assert actual == expected


class TestDifficulty:
    def test_levels(self):
        expected = {"beginner", "intermediate", "advanced"}
        actual = {d.value for d in Difficulty}
        assert actual == expected


# --- Topic model tests ---


class TestTopic:
    def _make_topic(self, **overrides):
        defaults = {
            "title": "What is RAG?",
            "category": Category.AI_ENGINEERING,
            "audience": "Software engineers",
            "difficulty": Difficulty.INTERMEDIATE,
            "hook": "Ever wonder how LLMs know what your docs say?",
        }
        defaults.update(overrides)
        return Topic(**defaults)

    def test_create_minimal(self):
        topic = self._make_topic()
        assert topic.title == "What is RAG?"
        assert topic.category == Category.AI_ENGINEERING
        assert topic.difficulty == Difficulty.INTERMEDIATE
        assert topic.status == TopicStatus.IDEA
        assert topic.source_refs == []
        assert topic.created_at is not None
        assert topic.updated_at is not None

    def test_id_auto_generated_and_unique(self):
        t1 = self._make_topic(title="A")
        t2 = self._make_topic(title="B")
        assert isinstance(t1.id, UUID)
        assert t1.id != t2.id

    def test_timestamps_are_utc_aware(self):
        topic = self._make_topic()
        assert topic.created_at.tzinfo is not None
        assert topic.updated_at.tzinfo is not None

    def test_created_at_close_to_now(self):
        before = datetime.now(UTC)
        topic = self._make_topic()
        after = datetime.now(UTC)
        assert before <= topic.created_at <= after

    def test_source_refs_default_empty_list(self):
        topic = self._make_topic()
        assert topic.source_refs == []

    def test_source_refs_accepts_list(self):
        topic = self._make_topic(source_refs=["src1", "src2"])
        assert topic.source_refs == ["src1", "src2"]

    def test_status_can_be_set_explicitly(self):
        topic = self._make_topic(status=TopicStatus.RESEARCHING)
        assert topic.status == TopicStatus.RESEARCHING

    def test_status_can_transition(self):
        topic = self._make_topic()
        topic.status = TopicStatus.SCRIPTED
        assert topic.status == TopicStatus.SCRIPTED

    def test_empty_title_rejected(self):
        with pytest.raises(ValidationError):
            self._make_topic(title="")

    def test_empty_hook_rejected(self):
        with pytest.raises(ValidationError):
            self._make_topic(hook="")


# --- ContentBrief tests ---


class TestContentBrief:
    def _make_brief(self, **overrides):
        defaults = {
            "topic": "What is RAG?",
            "problem": "LLMs hallucinate without context",
            "core_explanation": "RAG combines retrieval with generation",
            "example": "A chatbot fetching docs before answering",
            "takeaway": "RAG reduces hallucinations by grounding responses",
            "cta": "Try RAG in your next project",
            "sources": ["https://example.com"],
            "estimated_duration": 45,
            "visual_style": "Clean diagrams, dark theme",
        }
        defaults.update(overrides)
        return ContentBrief(**defaults)

    def test_create(self):
        brief = self._make_brief()
        assert brief.topic == "What is RAG?"
        assert brief.estimated_duration == 45
        assert brief.sources == ["https://example.com"]

    def test_sources_default_empty(self):
        brief = ContentBrief(
            topic="T",
            problem="P",
            core_explanation="E",
            example="Ex",
            takeaway="Tk",
            cta="C",
            estimated_duration=30,
            visual_style="Minimalist",
        )
        assert brief.sources == []

    def test_zero_duration_rejected(self):
        with pytest.raises(ValidationError):
            self._make_brief(estimated_duration=0)

    def test_negative_duration_rejected(self):
        with pytest.raises(ValidationError):
            self._make_brief(estimated_duration=-5)


# --- Script tests ---


class TestScript:
    def test_create_minimal(self):
        script = Script(brief_id=uuid4())
        assert isinstance(script.id, UUID)
        assert script.version == 1
        assert script.scenes == []

    def test_version_defaults_to_1(self):
        script = Script(brief_id=uuid4())
        assert script.version == 1

    def test_version_must_be_positive(self):
        with pytest.raises(ValidationError):
            Script(brief_id=uuid4(), version=0)

    def test_version_negative_rejected(self):
        with pytest.raises(ValidationError):
            Script(brief_id=uuid4(), version=-1)

    def test_scenes_list(self):
        scene = Scene(
            number=1,
            duration=5.0,
            narration="Hello",
            visual_prompt="A dog",
        )
        script = Script(brief_id=uuid4(), scenes=[scene])
        assert len(script.scenes) == 1
        assert script.scenes[0].number == 1


# --- Scene tests ---


class TestScene:
    def test_create_minimal(self):
        scene = Scene(
            number=1,
            duration=5.0,
            narration="Welcome to the video",
            visual_prompt="A dog coding",
        )
        assert scene.number == 1
        assert scene.duration == 5.0
        assert scene.narration == "Welcome to the video"
        assert scene.onscreen_text is None
        assert scene.transition is None

    def test_optional_fields(self):
        scene = Scene(
            number=2,
            duration=3.5,
            narration="Second scene",
            visual_prompt="Cats playing",
            onscreen_text="On-screen text",
            transition="fade",
        )
        assert scene.onscreen_text == "On-screen text"
        assert scene.transition == "fade"

    def test_number_must_be_positive(self):
        with pytest.raises(ValidationError):
            Scene(number=0, duration=5.0, narration="N", visual_prompt="V")

    def test_number_negative_rejected(self):
        with pytest.raises(ValidationError):
            Scene(number=-1, duration=5.0, narration="N", visual_prompt="V")

    def test_negative_duration_rejected(self):
        with pytest.raises(ValidationError):
            Scene(number=1, duration=-1.0, narration="N", visual_prompt="V")

    def test_empty_narration_rejected(self):
        with pytest.raises(ValidationError):
            Scene(number=1, duration=5.0, narration="", visual_prompt="V")

    def test_empty_visual_prompt_rejected(self):
        with pytest.raises(ValidationError):
            Scene(number=1, duration=5.0, narration="N", visual_prompt="")


# --- Serialization tests ---


class TestSerialization:
    def test_topic_model_dump(self):
        topic = Topic(
            title="Test",
            category=Category.AI_ENGINEERING,
            audience="Engineers",
            difficulty=Difficulty.BEGINNER,
            hook="H",
        )
        data = topic.model_dump()
        assert data["title"] == "Test"
        assert data["category"] == Category.AI_ENGINEERING
        assert data["status"] == TopicStatus.IDEA

    def test_topic_model_dump_json_uses_enum_values(self):
        topic = Topic(
            title="Test",
            category=Category.AI_ENGINEERING,
            audience="Engineers",
            difficulty=Difficulty.BEGINNER,
            hook="H",
        )
        data = topic.model_dump(mode="json")
        assert data["category"] == "ai_engineering"
        assert data["status"] == "IDEA"

    def test_topic_json_roundtrip(self):
        topic = Topic(
            title="Test",
            category=Category.ARCHITECTURE,
            audience="Engineers",
            difficulty=Difficulty.ADVANCED,
            hook="H",
        )
        json_str = topic.model_dump_json()
        restored = Topic.model_validate_json(json_str)
        assert restored.title == topic.title
        assert restored.category == topic.category
        assert restored.difficulty == topic.difficulty
        assert restored.status == topic.status
        assert restored.id == topic.id

    def test_script_json_roundtrip(self):
        scene = Scene(
            number=1,
            duration=10.0,
            narration="Hello world",
            visual_prompt="A cat",
            onscreen_text="Text",
            transition="cut",
        )
        script = Script(
            brief_id=uuid4(),
            version=2,
            scenes=[scene],
        )
        json_str = script.model_dump_json()
        restored = Script.model_validate_json(json_str)
        assert restored.version == 2
        assert len(restored.scenes) == 1
        assert restored.scenes[0].narration == "Hello world"
        assert restored.scenes[0].transition == "cut"
        assert restored.scenes[0].onscreen_text == "Text"

    def test_content_brief_json_roundtrip(self):
        brief = ContentBrief(
            topic="Test",
            problem="P",
            core_explanation="E",
            example="Ex",
            takeaway="Tk",
            cta="C",
            sources=["s1", "s2"],
            estimated_duration=30,
            visual_style="Minimal",
        )
        json_str = brief.model_dump_json()
        restored = ContentBrief.model_validate_json(json_str)
        assert restored.topic == "Test"
        assert restored.sources == ["s1", "s2"]
        assert restored.estimated_duration == 30

    def test_scene_json_roundtrip(self):
        scene = Scene(
            number=1,
            duration=5.0,
            narration="N",
            visual_prompt="V",
            onscreen_text="OT",
            transition="T",
        )
        json_str = scene.model_dump_json()
        restored = Scene.model_validate_json(json_str)
        assert restored.number == 1
        assert restored.narration == "N"
        assert restored.onscreen_text == "OT"
        assert restored.transition == "T"
