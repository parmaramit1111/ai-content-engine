"""Real-FFmpeg integration smoke test for the Phase 10 media pipeline.

Skips gracefully when ffmpeg/ffprobe are unavailable, so the rest of the
suite never depends on external tooling. Fixture clips are synthesized at
runtime via ffmpeg's own ``lavfi`` test-source filter — nothing binary is
committed to the repository.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from content_engine.application.video_assembly_service import VideoAssemblyService
from content_engine.domain.models import Scene, Storyboard

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

pytestmark = pytest.mark.skipif(
    not FFMPEG_AVAILABLE, reason="ffmpeg/ffprobe not available on PATH"
)


def _synthesize_clip(path: Path, duration: float) -> None:
    """Generate a tiny self-contained test clip via ffmpeg's lavfi testsrc."""
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


def test_real_ffmpeg_assembly_produces_9x16_mp4_and_srt(tmp_path: Path):
    asset_root = tmp_path / "assets"
    asset_root.mkdir()

    scenes = [
        Scene(number=1, duration=1.0, narration="Hook narration", visual_prompt="test"),
        Scene(number=2, duration=1.0, narration="Explanation narration", visual_prompt="test"),
    ]
    storyboard = Storyboard(script_id=uuid4(), scenes=scenes)

    clip1 = asset_root / "scene-1.mp4"
    clip2 = asset_root / "scene-2.mp4"
    _synthesize_clip(clip1, duration=1.0)
    _synthesize_clip(clip2, duration=1.0)

    from content_engine.domain.models import Asset

    assets = [
        Asset(
            storyboard_id=storyboard.id,
            scene_number=1,
            path=str(clip1),
            source="google_flow",
        ),
        Asset(
            storyboard_id=storyboard.id,
            scene_number=2,
            path=str(clip2),
            source="google_flow",
        ),
    ]

    service = VideoAssemblyService(asset_root=asset_root)

    production = service.assemble(storyboard, assets)

    output_path = Path(production.output_path)
    captions_path = Path(production.captions_path)

    assert output_path.exists()
    assert output_path.stat().st_size > 0
    assert captions_path.exists()
    assert captions_path.read_text().startswith("1\n")

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=s=x:p=0",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert probe.stdout.strip() == "1080x1920"
