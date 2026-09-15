"""CLI tests for asset import/validate, audio import, and assemble.

The real ``assemble`` success path uses real ffmpeg (skipped gracefully if
unavailable), synthesizing tiny fixture clips exactly like
``tests/integration/test_ffmpeg_smoke.py``. Everything else (asset/audio
import, validation failures, manifest errors) only needs a plausible file
on disk and never touches ffmpeg.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from typer.testing import CliRunner

from content_engine.cli import app
from content_engine.storage import ContentStore

runner = CliRunner()

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _env(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    content_root = tmp_path / "content"
    asset_root = tmp_path / "assets"
    monkeypatch.setenv("CONTENT_ROOT", str(content_root))
    monkeypatch.setenv("ASSET_ROOT", str(asset_root))
    return content_root, asset_root


def _extract(output: str, key: str) -> str:
    for line in output.splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    raise AssertionError(f"{key}= not found in output:\n{output}")


def _create_storyboard(content_root: Path, monkeypatch, scenes: list[dict]) -> str:
    """Build a Storyboard directly (bypassing topic/brief/script) for media tests.

    Media commands only need a persisted Storyboard; constructing one via
    ContentStore directly keeps these tests focused on the asset/audio/
    assemble commands rather than re-deriving the full generation pipeline.
    """
    from content_engine.domain.models import Scene, Script, Storyboard

    script = Script(brief_id=uuid4(), scenes=[Scene(**s) for s in scenes])
    storyboard = Storyboard(script_id=script.id, scenes=script.scenes)
    ContentStore(content_root).save_storyboard(storyboard)
    return str(storyboard.id)


def _two_scene_storyboard(content_root: Path, monkeypatch) -> str:
    return _create_storyboard(
        content_root,
        monkeypatch,
        [
            {"number": 1, "duration": 1.0, "narration": "Hook", "visual_prompt": "spinner"},
            {"number": 2, "duration": 1.0, "narration": "Explain", "visual_prompt": "diagram"},
        ],
    )


def _dummy_clip(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a real video, just bytes for extension/existence checks")
    return path


def _synthesize_clip(path: Path, duration: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={duration}:size=64x64:rate=5",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=8000:cl=mono",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


class TestAssetImport:
    def test_import_valid_clip(self, tmp_path, monkeypatch):
        content_root, asset_root = _env(monkeypatch, tmp_path)
        storyboard_id = _two_scene_storyboard(content_root, monkeypatch)
        clip = _dummy_clip(asset_root / "raw" / "scene-1.mp4")

        result = runner.invoke(
            app,
            [
                "asset",
                "import",
                "--storyboard-id",
                storyboard_id,
                "--scene-number",
                "1",
                "--path",
                str(clip),
                "--source",
                "google_flow",
                "--content-root",
                str(content_root),
                "--asset-root",
                str(asset_root),
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["scene_number"] == 1
        assert payload["source"] == "google_flow"

    def test_import_rejects_bad_extension_via_asset_service(self, tmp_path, monkeypatch):
        """The CLI must not duplicate AssetService's own extension validation."""
        content_root, asset_root = _env(monkeypatch, tmp_path)
        storyboard_id = _two_scene_storyboard(content_root, monkeypatch)
        clip = _dummy_clip(asset_root / "raw" / "scene-1.txt")

        result = runner.invoke(
            app,
            [
                "asset",
                "import",
                "--storyboard-id",
                storyboard_id,
                "--scene-number",
                "1",
                "--path",
                str(clip),
                "--source",
                "google_flow",
                "--content-root",
                str(content_root),
                "--asset-root",
                str(asset_root),
            ],
        )
        assert result.exit_code == 1
        assert "Unsupported video extension" in result.output

    def test_import_missing_storyboard_fails(self, tmp_path, monkeypatch):
        content_root, asset_root = _env(monkeypatch, tmp_path)

        result = runner.invoke(
            app,
            [
                "asset",
                "import",
                "--storyboard-id",
                str(uuid4()),
                "--scene-number",
                "1",
                "--path",
                "raw/scene-1.mp4",
                "--source",
                "google_flow",
                "--content-root",
                str(content_root),
                "--asset-root",
                str(asset_root),
            ],
        )
        assert result.exit_code == 1
        assert "Storyboard artifact not found" in result.output


class TestAssetValidate:
    def test_full_coverage_passes(self, tmp_path, monkeypatch):
        content_root, asset_root = _env(monkeypatch, tmp_path)
        storyboard_id = _two_scene_storyboard(content_root, monkeypatch)
        _dummy_clip(asset_root / "raw" / "scene-1.mp4")
        _dummy_clip(asset_root / "raw" / "scene-2.mp4")

        manifest = tmp_path / "assets.json"
        manifest.write_text(
            json.dumps(
                [
                    {"scene_number": 1, "path": "raw/scene-1.mp4", "source": "google_flow"},
                    {"scene_number": 2, "path": "raw/scene-2.mp4", "source": "google_flow"},
                ]
            )
        )

        result = runner.invoke(
            app,
            [
                "asset",
                "validate",
                "--storyboard-id",
                storyboard_id,
                "--manifest",
                str(manifest),
                "--content-root",
                str(content_root),
                "--asset-root",
                str(asset_root),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "scenes_covered=True" in result.output

    def test_missing_scene_fails(self, tmp_path, monkeypatch):
        content_root, asset_root = _env(monkeypatch, tmp_path)
        storyboard_id = _two_scene_storyboard(content_root, monkeypatch)
        _dummy_clip(asset_root / "raw" / "scene-1.mp4")

        manifest = tmp_path / "assets.json"
        manifest.write_text(
            json.dumps([{"scene_number": 1, "path": "raw/scene-1.mp4", "source": "google_flow"}])
        )

        result = runner.invoke(
            app,
            [
                "asset",
                "validate",
                "--storyboard-id",
                storyboard_id,
                "--manifest",
                str(manifest),
                "--content-root",
                str(content_root),
                "--asset-root",
                str(asset_root),
            ],
        )
        assert result.exit_code == 1
        assert "missing_scenes=[2]" in result.output

    def test_malformed_manifest_fails_clearly(self, tmp_path, monkeypatch):
        content_root, asset_root = _env(monkeypatch, tmp_path)
        storyboard_id = _two_scene_storyboard(content_root, monkeypatch)

        manifest = tmp_path / "assets.json"
        manifest.write_text("{not valid json")

        result = runner.invoke(
            app,
            [
                "asset",
                "validate",
                "--storyboard-id",
                storyboard_id,
                "--manifest",
                str(manifest),
                "--content-root",
                str(content_root),
                "--asset-root",
                str(asset_root),
            ],
        )
        assert result.exit_code == 1
        assert "Invalid JSON" in result.output

    def test_missing_manifest_file_fails_clearly(self, tmp_path, monkeypatch):
        content_root, asset_root = _env(monkeypatch, tmp_path)
        storyboard_id = _two_scene_storyboard(content_root, monkeypatch)

        result = runner.invoke(
            app,
            [
                "asset",
                "validate",
                "--storyboard-id",
                storyboard_id,
                "--manifest",
                str(tmp_path / "does-not-exist.json"),
                "--content-root",
                str(content_root),
                "--asset-root",
                str(asset_root),
            ],
        )
        assert result.exit_code == 1
        assert "File not found" in result.output


class TestAudioImport:
    def test_import_valid_audio(self, tmp_path, monkeypatch):
        content_root, asset_root = _env(monkeypatch, tmp_path)
        storyboard_id = _two_scene_storyboard(content_root, monkeypatch)
        audio = _dummy_clip(asset_root / "audio" / "narration.mp3")

        result = runner.invoke(
            app,
            [
                "audio",
                "import",
                "--storyboard-id",
                storyboard_id,
                "--path",
                str(audio),
                "--source",
                "human_narration",
                "--content-root",
                str(content_root),
                "--asset-root",
                str(asset_root),
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["source"] == "human_narration"

    def test_import_missing_storyboard_fails(self, tmp_path, monkeypatch):
        content_root, asset_root = _env(monkeypatch, tmp_path)

        result = runner.invoke(
            app,
            [
                "audio",
                "import",
                "--storyboard-id",
                str(uuid4()),
                "--path",
                "audio/narration.mp3",
                "--source",
                "human_narration",
                "--content-root",
                str(content_root),
                "--asset-root",
                str(asset_root),
            ],
        )
        assert result.exit_code == 1
        assert "Storyboard artifact not found" in result.output


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg/ffprobe not available on PATH")
class TestAssembleRealFfmpeg:
    def test_assembles_and_persists_production(self, tmp_path, monkeypatch):
        content_root, asset_root = _env(monkeypatch, tmp_path)
        storyboard_id = _two_scene_storyboard(content_root, monkeypatch)

        _synthesize_clip(asset_root / "raw" / "scene-1.mp4", 1.0)
        _synthesize_clip(asset_root / "raw" / "scene-2.mp4", 1.0)

        manifest = tmp_path / "assets.json"
        manifest.write_text(
            json.dumps(
                [
                    {"scene_number": 1, "path": "raw/scene-1.mp4", "source": "google_flow"},
                    {"scene_number": 2, "path": "raw/scene-2.mp4", "source": "google_flow"},
                ]
            )
        )

        result = runner.invoke(
            app,
            [
                "assemble",
                "--storyboard-id",
                storyboard_id,
                "--manifest",
                str(manifest),
                "--content-root",
                str(content_root),
                "--asset-root",
                str(asset_root),
            ],
        )
        assert result.exit_code == 0, result.output

        production_id = _extract(result.output, "production_id")
        output_path = Path(_extract(result.output, "output_path"))
        captions_path = Path(_extract(result.output, "captions_path"))

        assert output_path.exists() and output_path.stat().st_size > 0
        assert captions_path.exists() and captions_path.stat().st_size > 0

        store = ContentStore(content_root)
        production = store.load_production(UUID(production_id))
        assert production.output_path == str(output_path)
        assert len(production.asset_ids) == 2

    def test_missing_asset_for_scene_fails(self, tmp_path, monkeypatch):
        content_root, asset_root = _env(monkeypatch, tmp_path)
        storyboard_id = _two_scene_storyboard(content_root, monkeypatch)
        _synthesize_clip(asset_root / "raw" / "scene-1.mp4", 1.0)

        manifest = tmp_path / "assets.json"
        manifest.write_text(
            json.dumps([{"scene_number": 1, "path": "raw/scene-1.mp4", "source": "google_flow"}])
        )

        result = runner.invoke(
            app,
            [
                "assemble",
                "--storyboard-id",
                storyboard_id,
                "--manifest",
                str(manifest),
                "--content-root",
                str(content_root),
                "--asset-root",
                str(asset_root),
            ],
        )
        assert result.exit_code == 1
        assert "Missing asset for scene" in result.output


class TestAssembleAudioValidation:
    def test_audio_path_without_source_fails_clearly(self, tmp_path, monkeypatch):
        content_root, asset_root = _env(monkeypatch, tmp_path)
        storyboard_id = _two_scene_storyboard(content_root, monkeypatch)
        _dummy_clip(asset_root / "raw" / "scene-1.mp4")
        _dummy_clip(asset_root / "raw" / "scene-2.mp4")
        audio = _dummy_clip(asset_root / "audio" / "narration.mp3")

        manifest = tmp_path / "assets.json"
        manifest.write_text(
            json.dumps(
                [
                    {"scene_number": 1, "path": "raw/scene-1.mp4", "source": "google_flow"},
                    {"scene_number": 2, "path": "raw/scene-2.mp4", "source": "google_flow"},
                ]
            )
        )

        result = runner.invoke(
            app,
            [
                "assemble",
                "--storyboard-id",
                storyboard_id,
                "--manifest",
                str(manifest),
                "--audio-path",
                str(audio),
                "--content-root",
                str(content_root),
                "--asset-root",
                str(asset_root),
            ],
        )
        assert result.exit_code == 1
        assert "--audio-source is required" in result.output
