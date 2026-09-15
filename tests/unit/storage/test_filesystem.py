"""Unit tests for the filesystem-based content storage layer (Phase 12 foundation).

Covers:
- Round-trip save/load for Topic, ResearchNotes, ContentBrief, Script,
  Storyboard, Review — loaded objects must equal the originals exactly,
  including UUIDs and timestamps.
- Automatic subdirectory creation and the expected on-disk layout.
- Missing-artifact errors (no file, path is a directory).
- Malformed-artifact errors (invalid JSON, schema-invalid JSON).
- Overwrite-on-resave behavior.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from content_engine.domain.enums import (
    Category,
    Difficulty,
    ResearchVerificationStatus,
    ReviewCategory,
)
from content_engine.domain.models import (
    ChecklistItem,
    ContentBrief,
    ResearchNotes,
    Review,
    Scene,
    Script,
    Storyboard,
    Topic,
)
from content_engine.storage.filesystem import (
    ArtifactCorruptError,
    ArtifactNotFoundError,
    ContentStore,
)

# --- Builders (mirroring the conventions in tests/unit/test_*_models.py) ---


def _make_topic(**overrides) -> Topic:
    defaults: dict = {
        "title": "Why Database Indexes Make Queries Faster",
        "category": Category.BACKEND_ENGINEERING,
        "audience": "backend engineers",
        "difficulty": Difficulty.INTERMEDIATE,
        "hook": "Why does adding one line of SQL make queries 100x faster?",
        "source_refs": ["https://www.postgresql.org/docs/current/indexes.html"],
    }
    defaults.update(overrides)
    return Topic(**defaults)


def _make_research(topic_id, **overrides) -> ResearchNotes:
    defaults: dict = {
        "topic_id": topic_id,
        "key_facts": ["An index avoids a full table scan"],
        "terminology": ["B-tree: a balanced tree index structure"],
        "examples": ["EXPLAIN ANALYZE showing an Index Scan"],
        "caveats": ["Indexes slow down writes"],
        "primary_sources": ["https://www.postgresql.org/docs/current/indexes.html"],
        "visual_concepts": ["a book index vs. flipping every page"],
        "verification_status": ResearchVerificationStatus.VERIFIED,
    }
    defaults.update(overrides)
    return ResearchNotes(**defaults)


def _make_brief(**overrides) -> ContentBrief:
    defaults: dict = {
        "topic": "Why Database Indexes Make Queries Faster",
        "problem": "Full table scans are slow",
        "core_explanation": "Indexes let the database jump straight to matching rows",
        "example": "SELECT with and without an index on a large table",
        "takeaway": "Index your filter/sort columns",
        "cta": "Follow for more backend engineering tips",
        "sources": ["https://www.postgresql.org/docs/current/indexes.html"],
        "estimated_duration": 45,
        "visual_style": "clean animated diagrams",
    }
    defaults.update(overrides)
    return ContentBrief(**defaults)


def _make_scenes() -> list[Scene]:
    return [
        Scene(number=1, duration=3.0, narration="Hook", visual_prompt="a slow query spinner"),
        Scene(number=2, duration=10.0, narration="Explain", visual_prompt="a B-tree diagram"),
    ]


def _make_script(brief_id, **overrides) -> Script:
    defaults: dict = {"brief_id": brief_id, "scenes": _make_scenes()}
    defaults.update(overrides)
    return Script(**defaults)


def _make_storyboard(script_id, **overrides) -> Storyboard:
    defaults: dict = {"script_id": script_id, "scenes": _make_scenes()}
    defaults.update(overrides)
    return Storyboard(**defaults)


def _make_review(**overrides) -> Review:
    defaults: dict = {
        "production_id": uuid4(),
        "reviewer": "Amit Parmar",
        "checklist": {category: ChecklistItem(passed=True) for category in ReviewCategory},
    }
    defaults.update(overrides)
    return Review(**defaults)


# --- Round-trip tests ---


class TestRoundTrip:
    def test_topic(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        topic = _make_topic()

        store.save_topic(topic)
        restored = store.load_topic(topic.id)

        assert restored == topic

    def test_research_notes(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        research = _make_research(uuid4())

        store.save_research_notes(research)
        restored = store.load_research_notes(research.id)

        assert restored == research

    def test_content_brief(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        brief = _make_brief()

        store.save_content_brief(brief)
        restored = store.load_content_brief(brief.id)

        assert restored == brief

    def test_script(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        script = _make_script(uuid4())

        store.save_script(script)
        restored = store.load_script(script.id)

        assert restored == script
        assert restored.scenes == script.scenes

    def test_storyboard(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        storyboard = _make_storyboard(uuid4())

        store.save_storyboard(storyboard)
        restored = store.load_storyboard(storyboard.id)

        assert restored == storyboard
        assert restored.scenes == storyboard.scenes

    def test_review(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        review = _make_review()

        store.save_review(review)
        restored = store.load_review(review.id)

        assert restored == review
        assert set(restored.checklist.keys()) == set(ReviewCategory)


# --- Layout / directory creation ---


class TestArtifactLayout:
    @pytest.mark.parametrize(
        ("save_method", "subdir", "make_artifact"),
        [
            ("save_topic", "topics", lambda: _make_topic()),
            ("save_research_notes", "research", lambda: _make_research(uuid4())),
            ("save_content_brief", "briefs", lambda: _make_brief()),
            ("save_script", "scripts", lambda: _make_script(uuid4())),
            ("save_storyboard", "storyboards", lambda: _make_storyboard(uuid4())),
            ("save_review", "reviews", lambda: _make_review()),
        ],
    )
    def test_writes_under_expected_subdirectory(
        self, tmp_path: Path, save_method: str, subdir: str, make_artifact
    ):
        store = ContentStore(tmp_path)
        artifact = make_artifact()

        path = getattr(store, save_method)(artifact)

        assert path == tmp_path / subdir / f"{artifact.id}.json"
        assert path.is_file()

    def test_creates_directories_automatically(self, tmp_path: Path):
        content_root = tmp_path / "content"
        assert not content_root.exists()

        store = ContentStore(content_root)
        store.save_topic(_make_topic())

        assert (content_root / "topics").is_dir()

    def test_no_secrets_or_media_fields_written(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        topic = _make_topic()
        path = store.save_topic(topic)

        text = path.read_text(encoding="utf-8")
        assert "GEMINI_API_KEY" not in text
        assert "api_key" not in text.lower()


# --- Overwrite behavior ---


class TestOverwrite:
    def test_resaving_same_id_overwrites(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        topic = _make_topic()
        store.save_topic(topic)

        updated = topic.model_copy(update={"hook": "A brand new hook"})
        store.save_topic(updated)

        restored = store.load_topic(topic.id)
        assert restored.hook == "A brand new hook"


# --- Missing-artifact errors ---


class TestMissingArtifact:
    def test_load_topic_missing_raises(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        with pytest.raises(ArtifactNotFoundError, match="Topic artifact not found"):
            store.load_topic(uuid4())

    def test_load_research_notes_missing_raises(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        with pytest.raises(ArtifactNotFoundError, match="ResearchNotes artifact not found"):
            store.load_research_notes(uuid4())

    def test_load_content_brief_missing_raises(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        with pytest.raises(ArtifactNotFoundError, match="ContentBrief artifact not found"):
            store.load_content_brief(uuid4())

    def test_load_script_missing_raises(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        with pytest.raises(ArtifactNotFoundError, match="Script artifact not found"):
            store.load_script(uuid4())

    def test_load_storyboard_missing_raises(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        with pytest.raises(ArtifactNotFoundError, match="Storyboard artifact not found"):
            store.load_storyboard(uuid4())

    def test_load_review_missing_raises(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        with pytest.raises(ArtifactNotFoundError, match="Review artifact not found"):
            store.load_review(uuid4())

    def test_load_when_path_is_a_directory_raises(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        topic_id = uuid4()
        directory_path = tmp_path / "topics" / f"{topic_id}.json"
        directory_path.mkdir(parents=True)

        with pytest.raises(ArtifactNotFoundError):
            store.load_topic(topic_id)


# --- Malformed-artifact errors ---


class TestMalformedArtifact:
    def test_load_invalid_json_raises(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        topic_id = uuid4()
        bad_path = tmp_path / "topics" / f"{topic_id}.json"
        bad_path.parent.mkdir(parents=True)
        bad_path.write_text("{not valid json", encoding="utf-8")

        with pytest.raises(ArtifactCorruptError, match="Malformed Topic artifact"):
            store.load_topic(topic_id)

    def test_load_schema_invalid_json_raises(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        topic_id = uuid4()
        bad_path = tmp_path / "topics" / f"{topic_id}.json"
        bad_path.parent.mkdir(parents=True)
        # Valid JSON, but missing every required Topic field.
        bad_path.write_text("{}", encoding="utf-8")

        with pytest.raises(ArtifactCorruptError, match="Malformed Topic artifact"):
            store.load_topic(topic_id)

    def test_load_empty_file_raises(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        review_id = uuid4()
        bad_path = tmp_path / "reviews" / f"{review_id}.json"
        bad_path.parent.mkdir(parents=True)
        bad_path.write_text("", encoding="utf-8")

        with pytest.raises(ArtifactCorruptError, match="Malformed Review artifact"):
            store.load_review(review_id)
