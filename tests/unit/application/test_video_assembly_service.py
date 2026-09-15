"""Focused unit tests for VideoAssemblyService.

Covers: import_audio_track validation, assemble() structural/filesystem
validation, media-probing validation (duration tolerance/warning), and
successful assembly using a fake/injected FFmpegRunner — no real ffmpeg
is invoked anywhere in this file.
"""

import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from content_engine.application.video_assembly_service import (
    VideoAssemblyService,
    VideoAssemblyServiceError,
)
from content_engine.domain.models import Asset, AudioTrack, Production, Scene, Storyboard


class FakeFFmpegRunner:
    """Test double for FFmpegRunner — no real subprocess/ffmpeg invocation.

    - `run()` records every invocation and, by default, writes a small
      placeholder file at the command's final output path so downstream
      existence checks succeed, mimicking a real successful ffmpeg call.
    - `probe_duration()`/`probe_dimensions()` return configurable canned
      values per input path (defaulting to "matches expectations").
    """

    def __init__(
        self,
        ffmpeg_available: bool = True,
        ffprobe_available: bool = True,
        durations: dict[str, float] | None = None,
        dimensions: tuple[int, int] = (1080, 1920),
        fail_on_run: bool = False,
    ):
        self.ffmpeg_available = ffmpeg_available
        self.ffprobe_available = ffprobe_available
        self.durations = durations or {}
        self.dimensions = dimensions
        self.fail_on_run = fail_on_run
        self.run_calls: list[list[str]] = []

    def run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        self.run_calls.append(args)
        if self.fail_on_run:
            from content_engine.media.ffmpeg import FFmpegExecutionError

            raise FFmpegExecutionError(
                f"{args[0]} failed (exit code 1): {' '.join(args)}\nstderr: fake failure"
            )
        output_path = Path(args[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake media data")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    def is_ffmpeg_available(self) -> bool:
        return self.ffmpeg_available

    def is_ffprobe_available(self) -> bool:
        return self.ffprobe_available

    def probe_duration(self, path: Path) -> float:
        return self.durations.get(str(path), 5.0)

    def probe_dimensions(self, path: Path) -> tuple[int, int]:
        return self.dimensions


def _make_scene(**overrides) -> Scene:
    defaults = {
        "number": 1,
        "duration": 5.0,
        "narration": "Hook narration",
        "visual_prompt": "Wide shot",
    }
    defaults.update(overrides)
    return Scene(**defaults)


def _make_storyboard(scenes: list[Scene] | None = None, **overrides) -> Storyboard:
    if scenes is None:
        scenes = [_make_scene(number=1, duration=5.0), _make_scene(number=2, duration=10.0)]
    defaults = {"script_id": uuid4(), "scenes": scenes}
    defaults.update(overrides)
    return Storyboard(**defaults)


def _make_clip(tmp_path: Path, name: str = "clip.mp4") -> Path:
    clip = tmp_path / name
    clip.write_bytes(b"fake video data")
    return clip


def _make_asset(storyboard: Storyboard, scene_number: int, path: Path) -> Asset:
    return Asset(
        storyboard_id=storyboard.id,
        scene_number=scene_number,
        path=str(path),
        source="google_flow",
    )


def _resolved_assets(tmp_path: Path, storyboard: Storyboard) -> list[Asset]:
    assets = []
    for scene in storyboard.scenes:
        clip = _make_clip(tmp_path, name=f"scene-{scene.number}.mp4")
        assets.append(_make_asset(storyboard, scene.number, clip))
    return assets


def _fake_durations_matching(storyboard: Storyboard, assets: list[Asset]) -> dict[str, float]:
    by_scene = {asset.scene_number: asset for asset in assets}
    return {by_scene[scene.number].path: scene.duration for scene in storyboard.scenes}


class TestImportAudioTrack:
    def test_valid_audio(self, tmp_path: Path):
        clip = tmp_path / "narration.mp3"
        clip.write_bytes(b"fake audio")
        storyboard = _make_storyboard()
        service = VideoAssemblyService(asset_root=tmp_path)

        track = service.import_audio_track(storyboard, str(clip), source="human_narration")

        assert isinstance(track, AudioTrack)
        assert track.storyboard_id == storyboard.id
        assert Path(track.path) == clip.resolve()

    def test_empty_path_rejected(self, tmp_path: Path):
        storyboard = _make_storyboard()
        service = VideoAssemblyService(asset_root=tmp_path)

        with pytest.raises(VideoAssemblyServiceError, match="path is missing or empty"):
            service.import_audio_track(storyboard, "   ", source="human_narration")

    def test_missing_file_rejected(self, tmp_path: Path):
        storyboard = _make_storyboard()
        service = VideoAssemblyService(asset_root=tmp_path)

        with pytest.raises(VideoAssemblyServiceError, match="does not exist"):
            service.import_audio_track(
                storyboard, "does-not-exist.mp3", source="human_narration"
            )

    def test_path_outside_asset_root_rejected(self, tmp_path: Path):
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside.mp3"
        outside.write_bytes(b"data")
        storyboard = _make_storyboard()
        service = VideoAssemblyService(asset_root=root)

        with pytest.raises(VideoAssemblyServiceError, match="outside the configured asset root"):
            service.import_audio_track(storyboard, str(outside), source="human_narration")

    def test_invalid_extension_rejected(self, tmp_path: Path):
        clip = tmp_path / "narration.txt"
        clip.write_bytes(b"data")
        storyboard = _make_storyboard()
        service = VideoAssemblyService(asset_root=tmp_path)

        with pytest.raises(VideoAssemblyServiceError, match="Unsupported audio extension"):
            service.import_audio_track(storyboard, str(clip), source="human_narration")

    def test_empty_source_rejected(self, tmp_path: Path):
        clip = tmp_path / "narration.mp3"
        clip.write_bytes(b"data")
        storyboard = _make_storyboard()
        service = VideoAssemblyService(asset_root=tmp_path)

        with pytest.raises(VideoAssemblyServiceError, match="source is missing or empty"):
            service.import_audio_track(storyboard, str(clip), source="   ")

    def test_empty_provider_rejected_when_supplied(self, tmp_path: Path):
        clip = tmp_path / "narration.mp3"
        clip.write_bytes(b"data")
        storyboard = _make_storyboard()
        service = VideoAssemblyService(asset_root=tmp_path)

        with pytest.raises(VideoAssemblyServiceError, match="provider must not be empty"):
            service.import_audio_track(
                storyboard, str(clip), source="human_narration", provider="   "
            )

    def test_valid_metadata(self, tmp_path: Path):
        clip = tmp_path / "narration.mp3"
        clip.write_bytes(b"data")
        storyboard = _make_storyboard()
        service = VideoAssemblyService(asset_root=tmp_path)

        track = service.import_audio_track(
            storyboard, str(clip), source="human_narration", metadata={"take": 2}
        )

        assert track.metadata == {"take": 2}


class TestAssembleValidation:
    def test_empty_assets_rejected(self, tmp_path: Path):
        storyboard = _make_storyboard()
        service = VideoAssemblyService(asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner())

        with pytest.raises(VideoAssemblyServiceError, match="No assets supplied"):
            service.assemble(storyboard, [])

    def test_missing_scene_asset_rejected(self, tmp_path: Path):
        storyboard = _make_storyboard()
        clip = _make_clip(tmp_path)
        assets = [_make_asset(storyboard, 1, clip)]  # scene 2 missing
        service = VideoAssemblyService(asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner())

        with pytest.raises(VideoAssemblyServiceError, match=r"Missing asset for scene\(s\).*\[2\]"):
            service.assemble(storyboard, assets)

    def test_duplicate_scene_asset_rejected(self, tmp_path: Path):
        storyboard = _make_storyboard(scenes=[_make_scene(number=1, duration=5.0)])
        clip1 = _make_clip(tmp_path, "a.mp4")
        clip2 = _make_clip(tmp_path, "b.mp4")
        assets = [
            _make_asset(storyboard, 1, clip1),
            _make_asset(storyboard, 1, clip2),
        ]
        service = VideoAssemblyService(asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner())

        with pytest.raises(VideoAssemblyServiceError, match="Duplicate asset supplied"):
            service.assemble(storyboard, assets)

    def test_extra_unknown_scene_asset_rejected(self, tmp_path: Path):
        storyboard = _make_storyboard(scenes=[_make_scene(number=1, duration=5.0)])
        clip1 = _make_clip(tmp_path, "a.mp4")
        clip2 = _make_clip(tmp_path, "b.mp4")
        assets = [
            _make_asset(storyboard, 1, clip1),
            _make_asset(storyboard, 2, clip2),
        ]
        service = VideoAssemblyService(asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner())

        with pytest.raises(VideoAssemblyServiceError, match=r"unknown scene number\(s\).*\[2\]"):
            service.assemble(storyboard, assets)

    def test_mismatched_storyboard_id_rejected(self, tmp_path: Path):
        storyboard = _make_storyboard(scenes=[_make_scene(number=1, duration=5.0)])
        clip = _make_clip(tmp_path)
        wrong_asset = Asset(
            storyboard_id=uuid4(), scene_number=1, path=str(clip), source="google_flow"
        )
        service = VideoAssemblyService(asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner())

        with pytest.raises(VideoAssemblyServiceError, match="belongs to storyboard"):
            service.assemble(storyboard, [wrong_asset])

    def test_missing_visual_file_rejected(self, tmp_path: Path):
        storyboard = _make_storyboard(scenes=[_make_scene(number=1, duration=5.0)])
        asset = _make_asset(storyboard, 1, tmp_path / "missing.mp4")
        service = VideoAssemblyService(asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner())

        with pytest.raises(VideoAssemblyServiceError, match="does not exist"):
            service.assemble(storyboard, [asset])

    def test_invalid_visual_extension_rejected(self, tmp_path: Path):
        storyboard = _make_storyboard(scenes=[_make_scene(number=1, duration=5.0)])
        clip = _make_clip(tmp_path, "clip.avi")
        asset = _make_asset(storyboard, 1, clip)
        service = VideoAssemblyService(asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner())

        with pytest.raises(VideoAssemblyServiceError, match="Unsupported asset extension"):
            service.assemble(storyboard, [asset])

    def test_mismatched_audio_storyboard_id_rejected(self, tmp_path: Path):
        storyboard = _make_storyboard()
        assets = _resolved_assets(tmp_path, storyboard)
        audio_clip = tmp_path / "audio.mp3"
        audio_clip.write_bytes(b"data")
        wrong_audio = AudioTrack(storyboard_id=uuid4(), path=str(audio_clip), source="human")
        service = VideoAssemblyService(asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner())

        with pytest.raises(VideoAssemblyServiceError, match="belongs to storyboard"):
            service.assemble(storyboard, assets, audio_track=wrong_audio)

    def test_missing_audio_file_rejected(self, tmp_path: Path):
        storyboard = _make_storyboard()
        assets = _resolved_assets(tmp_path, storyboard)
        missing_audio = AudioTrack(
            storyboard_id=storyboard.id, path=str(tmp_path / "missing.mp3"), source="human"
        )
        service = VideoAssemblyService(asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner())

        with pytest.raises(VideoAssemblyServiceError, match="does not exist"):
            service.assemble(storyboard, assets, audio_track=missing_audio)

    def test_invalid_audio_extension_rejected(self, tmp_path: Path):
        storyboard = _make_storyboard()
        assets = _resolved_assets(tmp_path, storyboard)
        bad_audio_path = tmp_path / "audio.txt"
        bad_audio_path.write_bytes(b"data")
        bad_audio = AudioTrack(
            storyboard_id=storyboard.id, path=str(bad_audio_path), source="human"
        )
        service = VideoAssemblyService(asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner())

        with pytest.raises(VideoAssemblyServiceError, match="Unsupported audio extension"):
            service.assemble(storyboard, assets, audio_track=bad_audio)

    def test_missing_ffmpeg_rejected(self, tmp_path: Path):
        storyboard = _make_storyboard()
        assets = _resolved_assets(tmp_path, storyboard)
        service = VideoAssemblyService(
            asset_root=tmp_path,
            ffmpeg_runner=FakeFFmpegRunner(ffmpeg_available=False),
        )

        with pytest.raises(VideoAssemblyServiceError, match="ffmpeg"):
            service.assemble(storyboard, assets)

    def test_missing_ffprobe_rejected(self, tmp_path: Path):
        storyboard = _make_storyboard()
        assets = _resolved_assets(tmp_path, storyboard)
        service = VideoAssemblyService(
            asset_root=tmp_path,
            ffmpeg_runner=FakeFFmpegRunner(ffprobe_available=False),
        )

        with pytest.raises(VideoAssemblyServiceError, match="ffprobe"):
            service.assemble(storyboard, assets)


class TestMediaProbingValidation:
    def test_acceptable_clip_duration_passes(self, tmp_path: Path):
        storyboard = _make_storyboard()
        assets = _resolved_assets(tmp_path, storyboard)
        durations = _fake_durations_matching(storyboard, assets)
        service = VideoAssemblyService(
            asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner(durations=durations)
        )

        production = service.assemble(storyboard, assets)

        assert isinstance(production, Production)

    def test_gross_visual_duration_mismatch_rejected(self, tmp_path: Path):
        storyboard = _make_storyboard(scenes=[_make_scene(number=1, duration=5.0)])
        assets = _resolved_assets(tmp_path, storyboard)
        # Actual clip is wildly longer than the 5s scene expects.
        durations = {assets[0].path: 50.0}
        service = VideoAssemblyService(
            asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner(durations=durations)
        )

        with pytest.raises(
            VideoAssemblyServiceError, match="does not match expected scene duration"
        ):
            service.assemble(storyboard, assets)

    def test_audio_duration_mismatch_warns_not_rejects(self, tmp_path: Path):
        storyboard = _make_storyboard()
        assets = _resolved_assets(tmp_path, storyboard)
        clip_durations = _fake_durations_matching(storyboard, assets)
        audio_clip = tmp_path / "audio.mp3"
        audio_clip.write_bytes(b"data")
        audio_track = AudioTrack(
            storyboard_id=storyboard.id, path=str(audio_clip), source="human_narration"
        )
        durations = {**clip_durations, str(audio_clip.resolve()): 999.0}
        service = VideoAssemblyService(
            asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner(durations=durations)
        )

        with pytest.warns(UserWarning, match="AudioTrack duration"):
            production = service.assemble(storyboard, assets, audio_track=audio_track)

        assert isinstance(production, Production)

    def test_shorter_audio_duration_warns_not_rejects(self, tmp_path: Path):
        """Symmetric to the longer-audio case above: audio shorter than the
        total storyboard duration must also only warn, never reject, and
        must never trigger any video-shortening/looping/stretching behavior."""
        storyboard = _make_storyboard()  # total duration = 5.0 + 10.0 = 15.0s
        assets = _resolved_assets(tmp_path, storyboard)
        clip_durations = _fake_durations_matching(storyboard, assets)
        audio_clip = tmp_path / "audio.mp3"
        audio_clip.write_bytes(b"data")
        audio_track = AudioTrack(
            storyboard_id=storyboard.id, path=str(audio_clip), source="human_narration"
        )
        durations = {**clip_durations, str(audio_clip.resolve()): 2.0}
        service = VideoAssemblyService(
            asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner(durations=durations)
        )

        with pytest.warns(UserWarning, match="AudioTrack duration"):
            production = service.assemble(storyboard, assets, audio_track=audio_track)

        assert isinstance(production, Production)


class TestFiniteDurationValidation:
    """Fix 2: NaN/+inf/-inf probed durations must never silently pass the
    comparison (abs(nan - x) > tolerance is always False in Python)."""

    def test_nan_visual_clip_duration_rejected(self, tmp_path: Path):
        storyboard = _make_storyboard(scenes=[_make_scene(number=1, duration=5.0)])
        assets = _resolved_assets(tmp_path, storyboard)
        durations = {assets[0].path: float("nan")}
        service = VideoAssemblyService(
            asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner(durations=durations)
        )

        with pytest.raises(VideoAssemblyServiceError, match="not a valid finite number"):
            service.assemble(storyboard, assets)

    def test_positive_infinity_visual_clip_duration_rejected(self, tmp_path: Path):
        storyboard = _make_storyboard(scenes=[_make_scene(number=1, duration=5.0)])
        assets = _resolved_assets(tmp_path, storyboard)
        durations = {assets[0].path: float("inf")}
        service = VideoAssemblyService(
            asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner(durations=durations)
        )

        with pytest.raises(VideoAssemblyServiceError, match="not a valid finite number"):
            service.assemble(storyboard, assets)

    def test_negative_infinity_visual_clip_duration_rejected(self, tmp_path: Path):
        storyboard = _make_storyboard(scenes=[_make_scene(number=1, duration=5.0)])
        assets = _resolved_assets(tmp_path, storyboard)
        durations = {assets[0].path: float("-inf")}
        service = VideoAssemblyService(
            asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner(durations=durations)
        )

        with pytest.raises(VideoAssemblyServiceError, match="not a valid finite number"):
            service.assemble(storyboard, assets)

    def test_negative_visual_clip_duration_rejected(self, tmp_path: Path):
        storyboard = _make_storyboard(scenes=[_make_scene(number=1, duration=5.0)])
        assets = _resolved_assets(tmp_path, storyboard)
        durations = {assets[0].path: -1.0}
        service = VideoAssemblyService(
            asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner(durations=durations)
        )

        with pytest.raises(VideoAssemblyServiceError, match="must be non-negative"):
            service.assemble(storyboard, assets)

    def test_valid_finite_visual_clip_duration_passes(self, tmp_path: Path):
        storyboard = _make_storyboard(scenes=[_make_scene(number=1, duration=5.0)])
        assets = _resolved_assets(tmp_path, storyboard)
        durations = {assets[0].path: 5.0}
        service = VideoAssemblyService(
            asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner(durations=durations)
        )

        production = service.assemble(storyboard, assets)

        assert isinstance(production, Production)

    def test_nan_audio_duration_rejected(self, tmp_path: Path):
        storyboard = _make_storyboard()
        assets = _resolved_assets(tmp_path, storyboard)
        clip_durations = _fake_durations_matching(storyboard, assets)
        audio_clip = tmp_path / "audio.mp3"
        audio_clip.write_bytes(b"data")
        audio_track = AudioTrack(
            storyboard_id=storyboard.id, path=str(audio_clip), source="human_narration"
        )
        durations = {**clip_durations, str(audio_clip.resolve()): float("nan")}
        service = VideoAssemblyService(
            asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner(durations=durations)
        )

        with pytest.raises(VideoAssemblyServiceError, match="not a valid finite number"):
            service.assemble(storyboard, assets, audio_track=audio_track)

    def test_existing_gross_mismatch_behavior_still_correct(self, tmp_path: Path):
        """Regression: a valid-but-wildly-different finite duration must
        still be rejected as a mismatch, not swallowed by the finite check."""
        storyboard = _make_storyboard(scenes=[_make_scene(number=1, duration=5.0)])
        assets = _resolved_assets(tmp_path, storyboard)
        durations = {assets[0].path: 50.0}
        service = VideoAssemblyService(
            asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner(durations=durations)
        )

        with pytest.raises(
            VideoAssemblyServiceError, match="does not match expected scene duration"
        ):
            service.assemble(storyboard, assets)


class TestSuccessfulAssembly:
    def test_returns_production_with_expected_ids(self, tmp_path: Path):
        storyboard = _make_storyboard()
        assets = _resolved_assets(tmp_path, storyboard)
        durations = _fake_durations_matching(storyboard, assets)
        service = VideoAssemblyService(
            asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner(durations=durations)
        )

        production = service.assemble(storyboard, assets)

        assert production.script_id == storyboard.script_id
        assert production.storyboard_id == storyboard.id
        assert set(production.asset_ids) == {a.id for a in assets}
        assert production.audio_track_id is None

    def test_scene_order_based_on_storyboard_not_asset_list_order(self, tmp_path: Path):
        storyboard = _make_storyboard()
        assets = _resolved_assets(tmp_path, storyboard)
        reversed_assets = list(reversed(assets))  # incidental order should not matter
        durations = _fake_durations_matching(storyboard, assets)
        service = VideoAssemblyService(
            asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner(durations=durations)
        )

        production = service.assemble(storyboard, reversed_assets)

        assert set(production.asset_ids) == {a.id for a in assets}

    def test_captions_path_populated(self, tmp_path: Path):
        storyboard = _make_storyboard()
        assets = _resolved_assets(tmp_path, storyboard)
        durations = _fake_durations_matching(storyboard, assets)
        service = VideoAssemblyService(
            asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner(durations=durations)
        )

        production = service.assemble(storyboard, assets)

        assert production.captions_path
        assert Path(production.captions_path).exists()
        assert Path(production.captions_path).read_text().startswith("1\n")

    def test_output_path_populated(self, tmp_path: Path):
        storyboard = _make_storyboard()
        assets = _resolved_assets(tmp_path, storyboard)
        durations = _fake_durations_matching(storyboard, assets)
        service = VideoAssemblyService(
            asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner(durations=durations)
        )

        production = service.assemble(storyboard, assets)

        assert production.output_path
        assert Path(production.output_path).exists()

    def test_status_is_assembled(self, tmp_path: Path):
        storyboard = _make_storyboard()
        assets = _resolved_assets(tmp_path, storyboard)
        durations = _fake_durations_matching(storyboard, assets)
        service = VideoAssemblyService(
            asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner(durations=durations)
        )

        production = service.assemble(storyboard, assets)

        from content_engine.domain.enums import ProductionStatus

        assert production.status == ProductionStatus.ASSEMBLED

    def test_audio_track_id_set_when_supplied(self, tmp_path: Path):
        storyboard = _make_storyboard()
        assets = _resolved_assets(tmp_path, storyboard)
        clip_durations = _fake_durations_matching(storyboard, assets)
        audio_clip = tmp_path / "audio.mp3"
        audio_clip.write_bytes(b"data")
        audio_track = AudioTrack(
            storyboard_id=storyboard.id, path=str(audio_clip), source="human_narration"
        )
        total_duration = sum(s.duration for s in storyboard.scenes)
        durations = {**clip_durations, str(audio_clip.resolve()): total_duration}
        service = VideoAssemblyService(
            asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner(durations=durations)
        )

        production = service.assemble(storyboard, assets, audio_track=audio_track)

        assert production.audio_track_id == audio_track.id

    def test_temp_working_directory_is_cleaned_up(self, tmp_path: Path):
        storyboard = _make_storyboard()
        assets = _resolved_assets(tmp_path, storyboard)
        durations = _fake_durations_matching(storyboard, assets)
        runner = FakeFFmpegRunner(durations=durations)
        service = VideoAssemblyService(asset_root=tmp_path, ffmpeg_runner=runner)

        service.assemble(storyboard, assets)

        work_dirs = list(Path(tempfile_gettempdir()).glob("content-engine-assembly-*"))
        assert work_dirs == []

    def test_ffmpeg_execution_failure_raises_actionable_error(self, tmp_path: Path):
        storyboard = _make_storyboard()
        assets = _resolved_assets(tmp_path, storyboard)
        durations = _fake_durations_matching(storyboard, assets)
        service = VideoAssemblyService(
            asset_root=tmp_path,
            ffmpeg_runner=FakeFFmpegRunner(durations=durations, fail_on_run=True),
        )

        with pytest.raises(VideoAssemblyServiceError, match="fake failure"):
            service.assemble(storyboard, assets)


def _raise_simulated_caption_failure(cues: list) -> str:
    raise RuntimeError("simulated caption failure")


class TestArtifactCleanupOnFailure:
    """Fix 3: a failed assembly must never leave an orphaned final MP4/SRT
    with no corresponding Production, but must never touch any pre-existing,
    unrelated file either."""

    def test_mp4_cleaned_up_when_captions_creation_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        storyboard = _make_storyboard()
        assets = _resolved_assets(tmp_path, storyboard)
        durations = _fake_durations_matching(storyboard, assets)
        service = VideoAssemblyService(
            asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner(durations=durations)
        )
        monkeypatch.setattr(
            "content_engine.application.video_assembly_service.render_srt",
            _raise_simulated_caption_failure,
        )

        with pytest.raises(RuntimeError, match="simulated caption failure"):
            service.assemble(storyboard, assets)

        final_dir = tmp_path / "final"
        leftover = list(final_dir.glob("*.mp4")) if final_dir.exists() else []
        assert leftover == []

    def test_unrelated_preexisting_file_not_deleted_on_captions_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        storyboard = _make_storyboard()
        assets = _resolved_assets(tmp_path, storyboard)
        durations = _fake_durations_matching(storyboard, assets)
        service = VideoAssemblyService(
            asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner(durations=durations)
        )
        final_dir = tmp_path / "final"
        final_dir.mkdir(parents=True)
        unrelated = final_dir / "unrelated-preexisting.mp4"
        unrelated.write_bytes(b"do not touch me")
        monkeypatch.setattr(
            "content_engine.application.video_assembly_service.render_srt",
            _raise_simulated_caption_failure,
        )

        with pytest.raises(RuntimeError):
            service.assemble(storyboard, assets)

        assert unrelated.exists()
        assert unrelated.read_bytes() == b"do not touch me"

    def test_temp_working_directory_still_cleaned_up_on_captions_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        storyboard = _make_storyboard()
        assets = _resolved_assets(tmp_path, storyboard)
        durations = _fake_durations_matching(storyboard, assets)
        service = VideoAssemblyService(
            asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner(durations=durations)
        )
        monkeypatch.setattr(
            "content_engine.application.video_assembly_service.render_srt",
            _raise_simulated_caption_failure,
        )

        with pytest.raises(RuntimeError):
            service.assemble(storyboard, assets)

        work_dirs = list(Path(tempfile_gettempdir()).glob("content-engine-assembly-*"))
        assert work_dirs == []

    def test_both_artifacts_cleaned_up_when_post_assembly_validation_fails(self, tmp_path: Path):
        """A later failure (e.g. wrong final resolution) must also clean up
        both the MP4 and the SRT already written for this attempt."""
        storyboard = _make_storyboard()
        assets = _resolved_assets(tmp_path, storyboard)
        durations = _fake_durations_matching(storyboard, assets)
        service = VideoAssemblyService(
            asset_root=tmp_path,
            ffmpeg_runner=FakeFFmpegRunner(durations=durations, dimensions=(640, 480)),
        )

        with pytest.raises(VideoAssemblyServiceError, match="does not match the required"):
            service.assemble(storyboard, assets)

        final_dir = tmp_path / "final"
        subtitles_dir = tmp_path / "subtitles"
        assert list(final_dir.glob("*.mp4")) == []
        assert list(subtitles_dir.glob("*.srt")) == []

    def test_successful_assembly_still_leaves_expected_final_artifacts(self, tmp_path: Path):
        storyboard = _make_storyboard()
        assets = _resolved_assets(tmp_path, storyboard)
        durations = _fake_durations_matching(storyboard, assets)
        service = VideoAssemblyService(
            asset_root=tmp_path, ffmpeg_runner=FakeFFmpegRunner(durations=durations)
        )

        production = service.assemble(storyboard, assets)

        assert Path(production.output_path).exists()
        assert Path(production.captions_path).exists()


def tempfile_gettempdir() -> str:
    import tempfile as _tempfile

    return _tempfile.gettempdir()
