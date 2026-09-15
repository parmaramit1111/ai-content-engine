"""Unit tests for the filesystem-based content storage layer (Phase 12 foundation).

Covers:
- Round-trip save/load for Topic, ResearchNotes, ContentBrief, Script,
  Storyboard, Review, Production, PublicationPackage, WorkflowState,
  ExperimentRecord — loaded objects must equal the originals exactly,
  including UUIDs and timestamps. The last four extend the original Phase
  12 minimum (see ``ContentStore``'s docstring for why); WorkflowState/
  ExperimentRecord (Phase 12C) are keyed by ``topic_id`` instead of an
  ``.id`` field.
- Automatic subdirectory creation and the expected on-disk layout.
- Missing-artifact errors (no file, path is a directory).
- Malformed-artifact errors (invalid JSON, schema-invalid JSON).
- Overwrite-on-resave behavior.
- `list_experiment_records` (empty, multiple, one corrupt file).
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
from content_engine.domain.experiment import ExperimentRecord
from content_engine.domain.models import (
    ChecklistItem,
    ContentBrief,
    Production,
    PublicationPackage,
    ResearchNotes,
    Review,
    Scene,
    Script,
    Storyboard,
    Topic,
)
from content_engine.domain.workflow import WorkflowState
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


def _make_production(**overrides) -> Production:
    defaults: dict = {
        "script_id": uuid4(),
        "storyboard_id": uuid4(),
        "captions_path": "/assets/subtitles/prod-1.srt",
        "output_path": "/assets/final/prod-1.mp4",
    }
    defaults.update(overrides)
    return Production(**defaults)


def _make_package(**overrides) -> PublicationPackage:
    defaults: dict = {
        "production_id": uuid4(),
        "review_id": uuid4(),
        "output_path": "/assets/final/prod-1.mp4",
        "captions_path": "/assets/subtitles/prod-1.srt",
        "title": "Why Database Indexes Make Queries Faster",
    }
    defaults.update(overrides)
    return PublicationPackage(**defaults)


def _make_workflow_state(**overrides) -> WorkflowState:
    defaults: dict = {"topic_id": uuid4()}
    defaults.update(overrides)
    return WorkflowState(**defaults)


def _make_experiment_record(**overrides) -> ExperimentRecord:
    defaults: dict = {
        "topic_id": uuid4(),
        "title": "Why Database Indexes Make Queries Faster",
        "category": Category.BACKEND_ENGINEERING,
    }
    defaults.update(overrides)
    return ExperimentRecord(**defaults)


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

    def test_production(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        production = _make_production()

        store.save_production(production)
        restored = store.load_production(production.id)

        assert restored == production

    def test_publication_package(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        package = _make_package()

        store.save_publication_package(package)
        restored = store.load_publication_package(package.id)

        assert restored == package

    def test_workflow_state(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        state = _make_workflow_state(research_id=uuid4(), gemini_requests_used=3)

        store.save_workflow_state(state)
        restored = store.load_workflow_state(state.topic_id)

        assert restored == state

    def test_experiment_record(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        record = _make_experiment_record(regeneration_count=2, flow_credits_used=40)

        store.save_experiment_record(record)
        restored = store.load_experiment_record(record.topic_id)

        assert restored == record


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
            ("save_production", "productions", lambda: _make_production()),
            ("save_publication_package", "packages", lambda: _make_package()),
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

    @pytest.mark.parametrize(
        ("save_method", "subdir", "make_artifact"),
        [
            ("save_workflow_state", "workflow", lambda: _make_workflow_state()),
            ("save_experiment_record", "experiments", lambda: _make_experiment_record()),
        ],
    )
    def test_writes_under_expected_subdirectory_keyed_by_topic_id(
        self, tmp_path: Path, save_method: str, subdir: str, make_artifact
    ):
        store = ContentStore(tmp_path)
        artifact = make_artifact()

        path = getattr(store, save_method)(artifact)

        assert path == tmp_path / subdir / f"{artifact.topic_id}.json"
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

    def test_load_production_missing_raises(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        with pytest.raises(ArtifactNotFoundError, match="Production artifact not found"):
            store.load_production(uuid4())

    def test_load_publication_package_missing_raises(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        with pytest.raises(ArtifactNotFoundError, match="PublicationPackage artifact not found"):
            store.load_publication_package(uuid4())

    def test_load_workflow_state_missing_raises(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        with pytest.raises(ArtifactNotFoundError, match="WorkflowState artifact not found"):
            store.load_workflow_state(uuid4())

    def test_load_experiment_record_missing_raises(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        with pytest.raises(ArtifactNotFoundError, match="ExperimentRecord artifact not found"):
            store.load_experiment_record(uuid4())

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

    def test_load_workflow_state_malformed_raises(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        topic_id = uuid4()
        bad_path = tmp_path / "workflow" / f"{topic_id}.json"
        bad_path.parent.mkdir(parents=True)
        bad_path.write_text("{not valid json", encoding="utf-8")

        with pytest.raises(ArtifactCorruptError, match="Malformed WorkflowState artifact"):
            store.load_workflow_state(topic_id)


# --- ExperimentRecord listing ---


class TestListExperimentRecords:
    def test_empty_when_no_directory(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        assert store.list_experiment_records() == []

    def test_empty_when_directory_has_no_files(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        (tmp_path / "experiments").mkdir()
        assert store.list_experiment_records() == []

    def test_lists_all_records(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        first = _make_experiment_record(title="Video A")
        second = _make_experiment_record(title="Video B")
        store.save_experiment_record(first)
        store.save_experiment_record(second)

        records = store.list_experiment_records()

        assert {r.topic_id for r in records} == {first.topic_id, second.topic_id}

    def test_corrupt_record_raises_with_path(self, tmp_path: Path):
        store = ContentStore(tmp_path)
        store.save_experiment_record(_make_experiment_record())
        topic_id = uuid4()
        bad_path = tmp_path / "experiments" / f"{topic_id}.json"
        bad_path.write_text("{not valid json", encoding="utf-8")

        with pytest.raises(ArtifactCorruptError, match="Malformed ExperimentRecord artifact"):
            store.list_experiment_records()
