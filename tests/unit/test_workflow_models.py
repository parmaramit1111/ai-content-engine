"""Unit tests for the WorkflowState domain model (Phase 12C).

Covers: minimal/full construction, all-optional-except-topic_id defaults,
non-negative counter validation, and JSON round-trip.
"""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from content_engine.domain.workflow import WorkflowState


class TestWorkflowStateCreation:
    def test_minimal_creation_defaults(self):
        topic_id = uuid4()
        state = WorkflowState(topic_id=topic_id)

        assert state.topic_id == topic_id
        assert state.research_id is None
        assert state.brief_id is None
        assert state.script_id is None
        assert state.storyboard_id is None
        assert state.production_id is None
        assert state.review_id is None
        assert state.package_id is None
        assert state.asset_manifest_path is None
        assert state.audio_path is None
        assert state.brief_regenerations == 0
        assert state.script_regenerations == 0
        assert state.storyboard_regenerations == 0
        assert state.assemble_regenerations == 0
        assert state.gemini_requests_used == 0
        assert state.gemini_tokens_used == 0
        assert state.flow_credits_used == 0
        assert state.completed_at is None

    def test_full_creation(self):
        topic_id = uuid4()
        state = WorkflowState(
            topic_id=topic_id,
            research_id=uuid4(),
            brief_id=uuid4(),
            script_id=uuid4(),
            storyboard_id=uuid4(),
            production_id=uuid4(),
            review_id=uuid4(),
            package_id=uuid4(),
            asset_manifest_path="assets.json",
            audio_path="audio/narration.mp3",
            audio_source="human_narration",
            audio_provider="google_tts",
            brief_regenerations=2,
            script_regenerations=1,
            storyboard_regenerations=0,
            assemble_regenerations=3,
            gemini_requests_used=10,
            gemini_tokens_used=5000,
            flow_credits_used=80,
        )
        assert isinstance(state.research_id, UUID)
        assert state.brief_regenerations == 2
        assert state.gemini_tokens_used == 5000
        assert state.flow_credits_used == 80

    def test_missing_topic_id_raises(self):
        with pytest.raises(ValidationError, match="Field required"):
            WorkflowState()


class TestWorkflowStateValidation:
    @pytest.mark.parametrize(
        "field",
        [
            "brief_regenerations",
            "script_regenerations",
            "storyboard_regenerations",
            "assemble_regenerations",
            "gemini_requests_used",
            "gemini_tokens_used",
            "flow_credits_used",
        ],
    )
    def test_negative_counters_rejected(self, field):
        with pytest.raises(ValidationError):
            WorkflowState(topic_id=uuid4(), **{field: -1})


class TestWorkflowStateJSON:
    def test_json_round_trip(self):
        topic_id = uuid4()
        state = WorkflowState(
            topic_id=topic_id,
            research_id=uuid4(),
            brief_regenerations=1,
            gemini_requests_used=3,
            flow_credits_used=20,
        )
        data = state.model_dump_json()
        restored = WorkflowState.model_validate_json(data)

        assert restored == state
        assert restored.topic_id == topic_id
