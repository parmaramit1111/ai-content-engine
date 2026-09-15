"""Unit tests for deterministic caption/SRT derivation from a Storyboard.

Covers: single scene, multiple scenes, cumulative timestamps, SRT
formatting, numbering, narration text, scene order, millisecond
formatting, and deterministic repeated generation. Pure functions —
no subprocess, no filesystem, no providers.
"""

from uuid import uuid4

from content_engine.domain.models import Scene, Storyboard
from content_engine.media.captions import CaptionCue, build_caption_cues, render_srt


def _scene(**overrides) -> Scene:
    defaults = {
        "number": 1,
        "duration": 5.0,
        "narration": "Hook narration",
        "visual_prompt": "Wide shot",
    }
    defaults.update(overrides)
    return Scene(**defaults)


def _storyboard(scenes: list[Scene]) -> Storyboard:
    return Storyboard(script_id=uuid4(), scenes=scenes)


class TestBuildCaptionCues:
    def test_single_scene(self):
        storyboard = _storyboard([_scene(number=1, duration=5.0, narration="Hello there")])

        cues = build_caption_cues(storyboard)

        assert cues == [CaptionCue(index=1, start_seconds=0.0, end_seconds=5.0, text="Hello there")]

    def test_multiple_scenes_cumulative_timestamps(self):
        storyboard = _storyboard(
            [
                _scene(number=1, duration=5.0, narration="Hook"),
                _scene(number=2, duration=40.0, narration="Explanation"),
                _scene(number=3, duration=10.0, narration="Takeaway"),
            ]
        )

        cues = build_caption_cues(storyboard)

        assert cues[0] == CaptionCue(index=1, start_seconds=0.0, end_seconds=5.0, text="Hook")
        assert cues[1] == CaptionCue(
            index=2, start_seconds=5.0, end_seconds=45.0, text="Explanation"
        )
        assert cues[2] == CaptionCue(
            index=3, start_seconds=45.0, end_seconds=55.0, text="Takeaway"
        )

    def test_scene_order_is_trusted_not_resorted(self):
        """Even if scenes were (hypothetically) out of order, cues follow list order."""
        storyboard = _storyboard(
            [
                _scene(number=1, duration=5.0, narration="first"),
                _scene(number=2, duration=5.0, narration="second"),
            ]
        )

        cues = build_caption_cues(storyboard)

        assert [c.text for c in cues] == ["first", "second"]

    def test_narration_text_preserved_verbatim(self):
        storyboard = _storyboard(
            [_scene(number=1, narration="Ever wonder how LLMs know your docs?")]
        )

        cues = build_caption_cues(storyboard)

        assert cues[0].text == "Ever wonder how LLMs know your docs?"

    def test_empty_storyboard_returns_no_cues(self):
        storyboard = _storyboard([])
        assert build_caption_cues(storyboard) == []

    def test_deterministic_repeated_generation(self):
        storyboard = _storyboard(
            [_scene(number=1, duration=5.0), _scene(number=2, duration=10.0)]
        )

        assert build_caption_cues(storyboard) == build_caption_cues(storyboard)


class TestRenderSrt:
    def test_single_cue_formatting(self):
        cues = [CaptionCue(index=1, start_seconds=0.0, end_seconds=5.0, text="Hook narration")]

        srt = render_srt(cues)

        assert srt == "1\n00:00:00,000 --> 00:00:05,000\nHook narration\n\n"

    def test_multiple_cues_numbering_and_blank_line_separation(self):
        cues = [
            CaptionCue(index=1, start_seconds=0.0, end_seconds=5.0, text="Hook"),
            CaptionCue(index=2, start_seconds=5.0, end_seconds=45.0, text="Explanation"),
        ]

        srt = render_srt(cues)

        assert srt == (
            "1\n00:00:00,000 --> 00:00:05,000\nHook\n"
            "\n"
            "2\n00:00:05,000 --> 00:00:45,000\nExplanation\n\n"
        )

    def test_millisecond_formatting(self):
        cues = [CaptionCue(index=1, start_seconds=1.5, end_seconds=2.25, text="x")]

        srt = render_srt(cues)

        assert "00:00:01,500 --> 00:00:02,250" in srt

    def test_hours_and_minutes_formatting(self):
        cues = [CaptionCue(index=1, start_seconds=3725.0, end_seconds=3730.0, text="x")]

        srt = render_srt(cues)

        assert "01:02:05,000 --> 01:02:10,000" in srt

    def test_empty_cues_returns_empty_string(self):
        assert render_srt([]) == ""

    def test_deterministic_repeated_render(self):
        cues = [CaptionCue(index=1, start_seconds=0.0, end_seconds=5.0, text="Hook")]
        assert render_srt(cues) == render_srt(cues)

    def test_end_to_end_storyboard_to_srt(self):
        storyboard = _storyboard(
            [
                _scene(number=1, duration=5.0, narration="Hook"),
                _scene(number=2, duration=40.0, narration="Explanation"),
            ]
        )

        srt = render_srt(build_caption_cues(storyboard))

        assert srt.startswith("1\n00:00:00,000 --> 00:00:05,000\nHook\n")
        assert "2\n00:00:05,000 --> 00:00:45,000\nExplanation\n" in srt
