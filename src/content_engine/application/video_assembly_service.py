"""Video assembly service — validates inputs, orchestrates FFmpeg, returns a Production.

Implements the Phase 10 vertical slice:

    Storyboard + resolved one-per-scene Assets + optional AudioTrack
        → VideoAssemblyService.assemble()
        → structural + filesystem + media-probing validation
        → media/captions.py (deterministic SRT derivation)
        → media/assembly.py (FFmpeg command construction)
        → media/ffmpeg.py (FFmpeg execution)
        → Production (output_path, captions_path, status)

No provider, no budget-tracker, no CLI, no persistence beyond the final
media files themselves. Google Flow (and any TTS) stays fully
human-in-the-loop: this service only ever consumes already-produced clips
and audio files supplied by the caller — it never generates them, and it
never decides which of several candidate assets is "the" asset for a
scene (that selection happens entirely outside this service).
"""

from __future__ import annotations

import math
import shutil
import tempfile
import warnings
from pathlib import Path
from typing import Any
from uuid import uuid4

from content_engine.domain.models import Asset, AudioTrack, Production, Storyboard
from content_engine.media.assembly import (
    TARGET_HEIGHT,
    TARGET_WIDTH,
    build_concat_args,
    build_concat_list_content,
    build_mux_audio_args,
    build_scale_pad_args,
)
from content_engine.media.captions import build_caption_cues, render_srt
from content_engine.media.ffmpeg import FFmpegExecutionError, FFmpegRunner

_ALLOWED_VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".webm"})
_ALLOWED_AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".m4a", ".aac"})

# Gross-mismatch tolerance for a visual clip's real duration vs. its
# Scene.duration: the larger of a percentage of the expected duration or a
# fixed floor, so short scenes aren't held to an unreasonably tight bound.
_VIDEO_DURATION_TOLERANCE_RATIO = 0.2
_VIDEO_DURATION_TOLERANCE_MIN_SECONDS = 2.0

# Audio/total-duration mismatches only warn, never reject (see class docstring).
_AUDIO_DURATION_WARNING_THRESHOLD_SECONDS = 2.0


class VideoAssemblyServiceError(Exception):
    """Raised when validation, media probing, or FFmpeg assembly fails."""


class VideoAssemblyService:
    """Validate resolved assets/audio, assemble a 9:16 MP4, and generate SRT captions.

    No asset-selection heuristic: callers must supply exactly one visual
    Asset per storyboard scene. No TTS/audio generation: an AudioTrack, if
    supplied, must already reference an existing file.

    Args:
        asset_root: The configured local asset root (``AppSettings.asset_root``).
            All input/output paths must resolve inside this directory.
        ffmpeg_runner: Injectable FFmpeg/ffprobe runner; defaults to a real
            ``FFmpegRunner`` if not supplied.
    """

    def __init__(self, asset_root: Path, ffmpeg_runner: FFmpegRunner | None = None):
        self._asset_root = asset_root.resolve()
        self._ffmpeg = ffmpeg_runner or FFmpegRunner()

    # ---- Audio import ----

    def import_audio_track(
        self,
        storyboard: Storyboard,
        path: str,
        *,
        source: str,
        provider: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AudioTrack:
        """Validate a human-supplied narration/audio file and return an AudioTrack.

        Mirrors ``AssetService.import_asset``'s filesystem-validation style.
        No audio is synthesized here — the file must already exist.

        Raises:
            VideoAssemblyServiceError: If any validation step fails.
        """
        resolved_path = self._validate_and_resolve_path(path, _ALLOWED_AUDIO_EXTENSIONS, "Audio")
        validated_source = self._validate_non_empty(source, "source")
        validated_provider = self._validate_optional_non_empty(provider, "provider")

        return AudioTrack(
            storyboard_id=storyboard.id,
            path=str(resolved_path),
            source=validated_source,
            provider=validated_provider,
            metadata=metadata,
        )

    # ---- Assembly ----

    def assemble(
        self,
        storyboard: Storyboard,
        assets: list[Asset],
        audio_track: AudioTrack | None = None,
    ) -> Production:
        """Validate inputs, assemble a 9:16 MP4, generate SRT captions.

        Scene order always comes from ``storyboard.scenes`` — the incidental
        order of ``assets`` is never trusted; assets are looked up by
        ``scene_number`` and then iterated in storyboard order.

        Raises:
            VideoAssemblyServiceError: If any validation, probing, or
                FFmpeg step fails. No partial/failed Production is ever
                returned — failure always raises. Any final MP4/SRT this
                specific call already wrote before the failure is removed;
                pre-existing, unrelated files are never touched.
        """
        asset_by_scene = self._validate_assets(storyboard, assets)
        self._validate_audio(storyboard, audio_track)
        self._validate_tool_availability()
        self._validate_clip_durations(storyboard, asset_by_scene)
        self._validate_audio_duration(storyboard, audio_track)

        production_id = uuid4()
        # Deterministic, fresh-per-call paths — computed up front so cleanup
        # can target exactly the files *this* attempt may have created, even
        # if a later step fails before those paths are otherwise recorded.
        output_path = self._asset_root / "final" / f"{production_id}.mp4"
        captions_path = self._asset_root / "subtitles" / f"{production_id}.srt"

        work_dir = Path(tempfile.mkdtemp(prefix="content-engine-assembly-"))
        try:
            self._run_assembly(storyboard, asset_by_scene, audio_track, work_dir, output_path)
            self._write_captions(storyboard, captions_path)
            self._validate_output(output_path, captions_path)
        except Exception:
            self._cleanup_final_artifacts(output_path, captions_path)
            raise
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

        return Production(
            id=production_id,
            script_id=storyboard.script_id,
            storyboard_id=storyboard.id,
            asset_ids=[asset_by_scene[scene.number].id for scene in storyboard.scenes],
            audio_track_id=audio_track.id if audio_track else None,
            captions_path=str(captions_path),
            output_path=str(output_path),
        )

    @staticmethod
    def _cleanup_final_artifacts(output_path: Path, captions_path: Path) -> None:
        """Remove final artifacts this specific assembly attempt just created.

        Only ever removes the exact, freshly-computed (uuid4-based)
        ``output_path``/``captions_path`` for *this* call — paths that
        cannot collide with any pre-existing file. If a path was never
        actually written (the failure happened before that step), removal
        is a safe no-op.
        """
        for path in (output_path, captions_path):
            path.unlink(missing_ok=True)

    # ---- Pre-assembly validation ----

    def _validate_assets(self, storyboard: Storyboard, assets: list[Asset]) -> dict[int, Asset]:
        if not assets:
            raise VideoAssemblyServiceError("No assets supplied for assembly")

        by_scene: dict[int, Asset] = {}
        for asset in assets:
            if asset.storyboard_id != storyboard.id:
                raise VideoAssemblyServiceError(
                    f"Asset {asset.id} belongs to storyboard {asset.storyboard_id}, "
                    f"not the requested storyboard {storyboard.id}"
                )
            if asset.scene_number in by_scene:
                raise VideoAssemblyServiceError(
                    f"Duplicate asset supplied for scene {asset.scene_number}"
                )
            by_scene[asset.scene_number] = asset

        expected = {scene.number for scene in storyboard.scenes}
        actual = set(by_scene.keys())

        missing = sorted(expected - actual)
        if missing:
            raise VideoAssemblyServiceError(f"Missing asset for scene(s): {missing}")

        extra = sorted(actual - expected)
        if extra:
            raise VideoAssemblyServiceError(
                f"Asset(s) supplied for unknown scene number(s): {extra}"
            )

        for asset in by_scene.values():
            self._validate_existing_file(Path(asset.path), _ALLOWED_VIDEO_EXTENSIONS, "Asset")

        return by_scene

    def _validate_audio(self, storyboard: Storyboard, audio_track: AudioTrack | None) -> None:
        if audio_track is None:
            return
        if audio_track.storyboard_id != storyboard.id:
            raise VideoAssemblyServiceError(
                f"AudioTrack {audio_track.id} belongs to storyboard {audio_track.storyboard_id}, "
                f"not the requested storyboard {storyboard.id}"
            )
        self._validate_existing_file(Path(audio_track.path), _ALLOWED_AUDIO_EXTENSIONS, "Audio")

    def _validate_tool_availability(self) -> None:
        missing = []
        if not self._ffmpeg.is_ffmpeg_available():
            missing.append("ffmpeg")
        if not self._ffmpeg.is_ffprobe_available():
            missing.append("ffprobe")
        if missing:
            raise VideoAssemblyServiceError(
                f"Required tool(s) not found on PATH: {', '.join(missing)}"
            )

    # ---- FFmpeg/ffprobe boundary (translates FFmpegExecutionError explicitly) ----

    def _run(self, args: list[str]) -> None:
        try:
            self._ffmpeg.run(args)
        except FFmpegExecutionError as exc:
            raise VideoAssemblyServiceError(str(exc)) from exc

    def _probe_duration(self, path: Path) -> float:
        try:
            return self._ffmpeg.probe_duration(path)
        except FFmpegExecutionError as exc:
            raise VideoAssemblyServiceError(str(exc)) from exc

    def _probe_dimensions(self, path: Path) -> tuple[int, int]:
        try:
            return self._ffmpeg.probe_dimensions(path)
        except FFmpegExecutionError as exc:
            raise VideoAssemblyServiceError(str(exc)) from exc

    # ---- Media probing validation ----

    def _validate_clip_durations(
        self, storyboard: Storyboard, asset_by_scene: dict[int, Asset]
    ) -> None:
        for scene in storyboard.scenes:
            asset = asset_by_scene[scene.number]
            actual_duration = self._probe_duration(Path(asset.path))
            self._ensure_finite_duration(actual_duration, f"Scene {scene.number} asset")
            tolerance = max(
                scene.duration * _VIDEO_DURATION_TOLERANCE_RATIO,
                _VIDEO_DURATION_TOLERANCE_MIN_SECONDS,
            )
            if abs(actual_duration - scene.duration) > tolerance:
                raise VideoAssemblyServiceError(
                    f"Scene {scene.number} asset duration ({actual_duration:.2f}s) does not "
                    f"match expected scene duration ({scene.duration:.2f}s) within tolerance "
                    f"({tolerance:.2f}s): {asset.path}"
                )

    def _validate_audio_duration(
        self, storyboard: Storyboard, audio_track: AudioTrack | None
    ) -> None:
        if audio_track is None:
            return
        total_scene_duration = sum(scene.duration for scene in storyboard.scenes)
        actual_duration = self._probe_duration(Path(audio_track.path))
        self._ensure_finite_duration(actual_duration, "AudioTrack")
        if abs(actual_duration - total_scene_duration) > _AUDIO_DURATION_WARNING_THRESHOLD_SECONDS:
            warnings.warn(
                f"AudioTrack duration ({actual_duration:.2f}s) differs from total storyboard "
                f"duration ({total_scene_duration:.2f}s): {audio_track.path}",
                stacklevel=2,
            )

    @staticmethod
    def _ensure_finite_duration(value: float, label: str) -> None:
        """Reject NaN/±infinity/negative durations before any comparison.

        ``abs(nan - x) > tolerance`` is always False in Python, so a NaN
        probed duration would otherwise silently pass the mismatch check
        below rather than being treated as the invalid measurement it is.
        """
        if not math.isfinite(value):
            raise VideoAssemblyServiceError(
                f"{label} duration is not a valid finite number: {value}"
            )
        if value < 0:
            raise VideoAssemblyServiceError(f"{label} duration must be non-negative, got {value}")

    # ---- Execution ----

    def _run_assembly(
        self,
        storyboard: Storyboard,
        asset_by_scene: dict[int, Asset],
        audio_track: AudioTrack | None,
        work_dir: Path,
        output_path: Path,
    ) -> None:
        normalized_paths: list[Path] = []
        for scene in storyboard.scenes:
            asset = asset_by_scene[scene.number]
            normalized_path = work_dir / f"scene-{scene.number}.mp4"
            self._run(build_scale_pad_args(Path(asset.path), normalized_path))
            normalized_paths.append(normalized_path)

        concat_list_path = work_dir / "concat_list.txt"
        concat_list_path.write_text(build_concat_list_content(normalized_paths), encoding="utf-8")

        concatenated_path = work_dir / "concatenated.mp4"
        self._run(build_concat_args(concat_list_path, concatenated_path))

        output_path.parent.mkdir(parents=True, exist_ok=True)

        if audio_track is not None:
            self._run(build_mux_audio_args(concatenated_path, Path(audio_track.path), output_path))
        else:
            shutil.copy2(concatenated_path, output_path)

    def _write_captions(self, storyboard: Storyboard, captions_path: Path) -> None:
        cues = build_caption_cues(storyboard)
        srt_text = render_srt(cues)

        captions_path.parent.mkdir(parents=True, exist_ok=True)
        captions_path.write_text(srt_text, encoding="utf-8")

    # ---- Post-assembly validation ----

    def _validate_output(self, output_path: Path, captions_path: Path) -> None:
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise VideoAssemblyServiceError(
                f"FFmpeg reported success but produced no usable output: {output_path}"
            )
        if not captions_path.exists() or captions_path.stat().st_size == 0:
            raise VideoAssemblyServiceError(f"Captions file was not produced: {captions_path}")

        width, height = self._probe_dimensions(output_path)
        if (width, height) != (TARGET_WIDTH, TARGET_HEIGHT):
            raise VideoAssemblyServiceError(
                f"Final output resolution {width}x{height} does not match the required "
                f"9:16 target {TARGET_WIDTH}x{TARGET_HEIGHT}: {output_path}"
            )

    # ---- Shared filesystem/metadata validators ----

    def _validate_and_resolve_path(
        self, path: str, allowed_extensions: frozenset[str], label: str
    ) -> Path:
        if not isinstance(path, str) or not path.strip():
            raise VideoAssemblyServiceError(f"{label} path is missing or empty")

        candidate = Path(path.strip())
        if not candidate.is_absolute():
            candidate = self._asset_root / candidate
        resolved = candidate.resolve()

        try:
            resolved.relative_to(self._asset_root)
        except ValueError as exc:
            raise VideoAssemblyServiceError(
                f"{label} path {resolved} resolves outside the configured asset root "
                f"{self._asset_root}"
            ) from exc

        self._validate_existing_file(resolved, allowed_extensions, label)
        return resolved

    @staticmethod
    def _validate_existing_file(path: Path, allowed_extensions: frozenset[str], label: str) -> None:
        if not path.exists():
            raise VideoAssemblyServiceError(f"{label} file does not exist: {path}")
        if not path.is_file():
            raise VideoAssemblyServiceError(f"{label} path is not a regular file: {path}")
        if path.suffix.lower() not in allowed_extensions:
            raise VideoAssemblyServiceError(
                f"Unsupported {label.lower()} extension '{path.suffix}' for {path}; "
                f"must be one of {sorted(allowed_extensions)}"
            )

    @staticmethod
    def _validate_non_empty(value: Any, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise VideoAssemblyServiceError(f"{field_name} is missing or empty")
        return value.strip()

    @staticmethod
    def _validate_optional_non_empty(value: str | None, field_name: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise VideoAssemblyServiceError(f"{field_name} must not be empty when supplied")
        return value.strip()
