"""Unit tests for the AudioTrack domain model.

Covers:
- valid creation, id auto-generation, storyboard_id association
- required field enforcement (storyboard_id, path, source)
- optional provider/metadata handling
- JSON round-trip
"""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from content_engine.domain.models import AudioTrack


def _make_audio_track(**overrides) -> AudioTrack:
    defaults = {
        "storyboard_id": uuid4(),
        "path": "/assets/audio/narration.mp3",
        "source": "human_narration",
    }
    defaults.update(overrides)
    return AudioTrack(**defaults)


class TestAudioTrackCreation:
    def test_valid_creation(self):
        track = _make_audio_track()
        assert isinstance(track, AudioTrack)
        assert isinstance(track.id, UUID)
        assert track.path == "/assets/audio/narration.mp3"
        assert track.source == "human_narration"

    def test_id_auto_generated_and_unique(self):
        t1 = _make_audio_track()
        t2 = _make_audio_track()
        assert t1.id != t2.id

    def test_storyboard_id_association(self):
        storyboard_id = uuid4()
        track = _make_audio_track(storyboard_id=storyboard_id)
        assert track.storyboard_id == storyboard_id

    def test_optional_fields_default_to_none(self):
        track = _make_audio_track()
        assert track.provider is None
        assert track.metadata is None

    def test_optional_fields_accepted(self):
        track = _make_audio_track(provider="google_tts", metadata={"voice": "en-US"})
        assert track.provider == "google_tts"
        assert track.metadata == {"voice": "en-US"}

    def test_created_at_is_set(self):
        track = _make_audio_track()
        assert track.created_at is not None


class TestAudioTrackValidation:
    def test_missing_storyboard_id_raises(self):
        with pytest.raises(ValidationError, match="Field required"):
            AudioTrack(path="/assets/audio/x.mp3", source="human_narration")

    def test_missing_path_raises(self):
        with pytest.raises(ValidationError, match="Field required"):
            AudioTrack(storyboard_id=uuid4(), source="human_narration")

    def test_missing_source_raises(self):
        with pytest.raises(ValidationError, match="Field required"):
            AudioTrack(storyboard_id=uuid4(), path="/assets/audio/x.mp3")


class TestAudioTrackJSON:
    def test_json_round_trip(self):
        track = _make_audio_track(provider="google_tts")
        data = track.model_dump_json()
        restored = AudioTrack.model_validate_json(data)
        assert restored.id == track.id
        assert restored.storyboard_id == track.storyboard_id
        assert restored.provider == "google_tts"
