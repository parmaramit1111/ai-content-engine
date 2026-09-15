"""Unit tests for the Asset domain model and AssetType enum.

Covers:
- valid creation, id auto-generation, storyboard_id/scene_number association
- default type is VIDEO
- required field enforcement (storyboard_id, scene_number, path, source)
- scene_number and flow_credits_used range/type validation at the model level
- optional provider/metadata handling
- JSON round-trip
"""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from content_engine.domain.enums import AssetType
from content_engine.domain.models import Asset


def _make_asset(**overrides) -> Asset:
    defaults = {
        "storyboard_id": uuid4(),
        "scene_number": 1,
        "path": "/assets/clips/scene-1.mp4",
        "source": "google_flow",
    }
    defaults.update(overrides)
    return Asset(**defaults)


class TestAssetTypeEnum:
    def test_video_value(self):
        assert AssetType.VIDEO == "video"

    def test_has_exactly_one_value(self):
        assert {t.value for t in AssetType} == {"video"}


class TestAssetCreation:
    def test_valid_creation(self):
        asset = _make_asset()
        assert isinstance(asset, Asset)
        assert isinstance(asset.id, UUID)
        assert asset.scene_number == 1
        assert asset.path == "/assets/clips/scene-1.mp4"
        assert asset.source == "google_flow"

    def test_id_auto_generated_and_unique(self):
        a1 = _make_asset()
        a2 = _make_asset()
        assert a1.id != a2.id

    def test_default_type_is_video(self):
        asset = _make_asset()
        assert asset.type == AssetType.VIDEO

    def test_storyboard_id_association(self):
        storyboard_id = uuid4()
        asset = _make_asset(storyboard_id=storyboard_id)
        assert asset.storyboard_id == storyboard_id

    def test_optional_fields_default_to_none(self):
        asset = _make_asset()
        assert asset.provider is None
        assert asset.flow_credits_used is None
        assert asset.metadata is None

    def test_optional_fields_accepted(self):
        asset = _make_asset(
            provider="veo-3.1-fast",
            flow_credits_used=20,
            metadata={"attempt": 2},
        )
        assert asset.provider == "veo-3.1-fast"
        assert asset.flow_credits_used == 20
        assert asset.metadata == {"attempt": 2}

    def test_created_at_is_set(self):
        asset = _make_asset()
        assert asset.created_at is not None


class TestAssetValidation:
    def test_missing_storyboard_id_raises(self):
        with pytest.raises(ValidationError, match="Field required"):
            Asset(scene_number=1, path="/assets/x.mp4", source="google_flow")

    def test_missing_scene_number_raises(self):
        with pytest.raises(ValidationError, match="Field required"):
            Asset(storyboard_id=uuid4(), path="/assets/x.mp4", source="google_flow")

    def test_missing_path_raises(self):
        with pytest.raises(ValidationError, match="Field required"):
            Asset(storyboard_id=uuid4(), scene_number=1, source="google_flow")

    def test_missing_source_raises(self):
        with pytest.raises(ValidationError, match="Field required"):
            Asset(storyboard_id=uuid4(), scene_number=1, path="/assets/x.mp4")

    def test_scene_number_below_one_rejected(self):
        with pytest.raises(ValidationError):
            _make_asset(scene_number=0)

    def test_flow_credits_below_one_rejected(self):
        with pytest.raises(ValidationError):
            _make_asset(flow_credits_used=0)

    def test_invalid_asset_type_rejected(self):
        with pytest.raises(ValidationError):
            _make_asset(type="image")


class TestAssetJSON:
    def test_json_round_trip(self):
        asset = _make_asset(provider="veo-3.1-fast", flow_credits_used=20)
        data = asset.model_dump_json()
        restored = Asset.model_validate_json(data)
        assert restored.id == asset.id
        assert restored.storyboard_id == asset.storyboard_id
        assert restored.scene_number == asset.scene_number
        assert restored.provider == "veo-3.1-fast"
        assert restored.flow_credits_used == 20
