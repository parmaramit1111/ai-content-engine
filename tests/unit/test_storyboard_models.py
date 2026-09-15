"""Unit tests for the Storyboard domain model.

Covers:
- valid creation, id auto-generation, script_id association
- scenes accepts a list of valid Scene objects, in order
- empty scenes list allowed (matches Script.scenes' own lack of a constraint)
- invalid nested scene data rejected via Pydantic
- JSON round-trip
"""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from content_engine.domain.models import Scene, Storyboard


def _scene(**overrides) -> Scene:
    defaults = {
        "number": 1,
        "duration": 5.0,
        "narration": "Hook narration",
        "visual_prompt": "Wide shot of a robot thinking",
    }
    defaults.update(overrides)
    return Scene(**defaults)


class TestStoryboardCreation:
    def test_valid_creation(self):
        storyboard = Storyboard(script_id=uuid4(), scenes=[_scene()])
        assert isinstance(storyboard, Storyboard)
        assert isinstance(storyboard.id, UUID)
        assert len(storyboard.scenes) == 1

    def test_id_auto_generated_and_unique(self):
        script_id = uuid4()
        s1 = Storyboard(script_id=script_id, scenes=[_scene()])
        s2 = Storyboard(script_id=script_id, scenes=[_scene()])
        assert s1.id != s2.id

    def test_script_id_association(self):
        script_id = uuid4()
        storyboard = Storyboard(script_id=script_id, scenes=[_scene()])
        assert storyboard.script_id == script_id

    def test_empty_scenes_allowed(self):
        """Matches Script.scenes, which also has no min-length constraint."""
        storyboard = Storyboard(script_id=uuid4())
        assert storyboard.scenes == []

    def test_scenes_preserve_order(self):
        scenes = [
            _scene(number=1, narration="first"),
            _scene(number=2, narration="second"),
            _scene(number=3, narration="third"),
        ]
        storyboard = Storyboard(script_id=uuid4(), scenes=scenes)
        assert [s.narration for s in storyboard.scenes] == ["first", "second", "third"]


class TestStoryboardValidation:
    def test_missing_script_id_raises(self):
        with pytest.raises(ValidationError, match="Field required"):
            Storyboard(scenes=[_scene()])

    def test_invalid_scene_data_rejected(self):
        with pytest.raises(ValidationError):
            Storyboard(script_id=uuid4(), scenes=[{"number": 1}])  # missing required Scene fields

    def test_scenes_must_be_list_of_scene(self):
        with pytest.raises(ValidationError):
            Storyboard(script_id=uuid4(), scenes=["not-a-scene"])


class TestStoryboardJSON:
    def test_json_round_trip(self):
        storyboard = Storyboard(script_id=uuid4(), scenes=[_scene(), _scene(number=2)])
        data = storyboard.model_dump_json()
        restored = Storyboard.model_validate_json(data)
        assert restored.id == storyboard.id
        assert restored.script_id == storyboard.script_id
        assert len(restored.scenes) == 2
        assert restored.scenes[1].number == 2
