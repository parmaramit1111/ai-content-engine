"""Unit tests for the Production domain model and ProductionStatus enum.

Covers:
- valid creation, id auto-generation, id-only references
- default status is ASSEMBLED
- required field enforcement
- JSON round-trip
"""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from content_engine.domain.enums import ProductionStatus
from content_engine.domain.models import Production


def _make_production(**overrides) -> Production:
    defaults = {
        "script_id": uuid4(),
        "storyboard_id": uuid4(),
        "asset_ids": [uuid4(), uuid4()],
        "captions_path": "/assets/subtitles/prod-1.srt",
        "output_path": "/assets/final/prod-1.mp4",
    }
    defaults.update(overrides)
    return Production(**defaults)


class TestProductionStatusEnum:
    def test_assembled_value(self):
        assert ProductionStatus.ASSEMBLED == "assembled"

    def test_has_exactly_one_value(self):
        assert {s.value for s in ProductionStatus} == {"assembled"}


class TestProductionCreation:
    def test_valid_creation(self):
        production = _make_production()
        assert isinstance(production, Production)
        assert isinstance(production.id, UUID)
        assert len(production.asset_ids) == 2

    def test_id_auto_generated_and_unique(self):
        p1 = _make_production()
        p2 = _make_production()
        assert p1.id != p2.id

    def test_default_status_is_assembled(self):
        production = _make_production()
        assert production.status == ProductionStatus.ASSEMBLED

    def test_audio_track_id_defaults_to_none(self):
        production = _make_production()
        assert production.audio_track_id is None

    def test_audio_track_id_accepted(self):
        audio_track_id = uuid4()
        production = _make_production(audio_track_id=audio_track_id)
        assert production.audio_track_id == audio_track_id

    def test_references_are_ids_only(self):
        """Production stores ids, not embedded Asset/Storyboard/Script objects."""
        production = _make_production()
        assert all(isinstance(asset_id, UUID) for asset_id in production.asset_ids)
        assert isinstance(production.script_id, UUID)
        assert isinstance(production.storyboard_id, UUID)

    def test_created_at_is_set(self):
        production = _make_production()
        assert production.created_at is not None


class TestProductionValidation:
    def test_missing_script_id_raises(self):
        with pytest.raises(ValidationError, match="Field required"):
            Production(
                storyboard_id=uuid4(),
                captions_path="/x.srt",
                output_path="/x.mp4",
            )

    def test_missing_storyboard_id_raises(self):
        with pytest.raises(ValidationError, match="Field required"):
            Production(
                script_id=uuid4(),
                captions_path="/x.srt",
                output_path="/x.mp4",
            )

    def test_missing_captions_path_raises(self):
        with pytest.raises(ValidationError, match="Field required"):
            Production(script_id=uuid4(), storyboard_id=uuid4(), output_path="/x.mp4")

    def test_missing_output_path_raises(self):
        with pytest.raises(ValidationError, match="Field required"):
            Production(script_id=uuid4(), storyboard_id=uuid4(), captions_path="/x.srt")

    def test_empty_asset_ids_allowed_at_model_level(self):
        """Model-level: service-level validation (not the model) enforces coverage."""
        production = _make_production(asset_ids=[])
        assert production.asset_ids == []


class TestProductionJSON:
    def test_json_round_trip(self):
        production = _make_production(audio_track_id=uuid4())
        data = production.model_dump_json()
        restored = Production.model_validate_json(data)
        assert restored.id == production.id
        assert restored.script_id == production.script_id
        assert restored.storyboard_id == production.storyboard_id
        assert restored.asset_ids == production.asset_ids
        assert restored.audio_track_id == production.audio_track_id
        assert restored.status == ProductionStatus.ASSEMBLED
