"""FFmpeg command construction — pure, no subprocess execution.

Builds argument lists for the three assembly operations Phase 10 needs:
scaling/padding a clip to the target 9:16 resolution, concatenating
ordered clips, and muxing an optional audio track. Never touches the
filesystem beyond the path strings it's given, and never invokes
``subprocess`` itself — that's ``media/ffmpeg.py``'s job. Every builder
here returns a plain ``list[str]``; paths are never shell-interpolated.

Every clip is normalized to identical video AND audio codec parameters
(not just spatial dimensions) before concatenation, because the concat
step uses the concat demuxer with ``-c copy`` (pure stream copy) — which
requires matching codec/pixel-format/frame-rate/audio parameters across
every input. Google Flow (and other human-supplied) clips are expected to
arrive with heterogeneous original encodings, so normalization must fix
more than just width/height for the later stream-copy concat to be valid.
"""

from __future__ import annotations

from pathlib import Path

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
TARGET_FRAME_RATE = 30

VIDEO_CODEC = "libx264"
PIXEL_FORMAT = "yuv420p"

AUDIO_CODEC = "aac"
AUDIO_SAMPLE_RATE = 48000
AUDIO_CHANNELS = 2


def build_scale_pad_args(input_path: Path, output_path: Path) -> list[str]:
    """Build ffmpeg args to fully normalize a clip for stream-copy concat.

    Scales down to fit within the target 9:16 box preserving aspect ratio,
    pads with black to reach the exact target dimensions, and forces a
    deterministic frame rate — then re-encodes with a fixed video codec/
    pixel format and a fixed audio codec/sample rate/channel layout, so
    every normalized clip shares identical parameters regardless of its
    original source encoding. Audio is never blindly copied (``-c:a copy``
    would let incompatible source audio through unchanged).
    """
    video_filter = (
        f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={TARGET_FRAME_RATE}"
    )
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vf",
        video_filter,
        "-c:v",
        VIDEO_CODEC,
        "-pix_fmt",
        PIXEL_FORMAT,
        "-c:a",
        AUDIO_CODEC,
        "-ar",
        str(AUDIO_SAMPLE_RATE),
        "-ac",
        str(AUDIO_CHANNELS),
        str(output_path),
    ]


def _escape_concat_path(path: Path) -> str:
    """Escape a path for the ffmpeg concat demuxer's quoted file format."""
    return str(path).replace("'", "'\\''")


def build_concat_list_content(clip_paths: list[Path]) -> str:
    """Build the concat demuxer's input file-list content."""
    lines = [f"file '{_escape_concat_path(path)}'" for path in clip_paths]
    return "\n".join(lines) + ("\n" if lines else "")


def build_concat_args(concat_list_path: Path, output_path: Path) -> list[str]:
    """Build ffmpeg args to concatenate clips listed in a concat demuxer file."""
    return [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list_path),
        "-c",
        "copy",
        str(output_path),
    ]


def build_mux_audio_args(video_path: Path, audio_path: Path, output_path: Path) -> list[str]:
    """Build ffmpeg args to mux an audio track onto an already-assembled video.

    Deliberately omits ``-shortest``: that flag would silently truncate
    whichever stream is longer (most commonly, cutting off the tail of
    narration audio that runs longer than the assembled video). Without
    it, ffmpeg's default multi-input muxing behavior keeps both streams
    for their own full length — the container's duration follows the
    longer of the two, and neither is silently cut short. Any real
    audio/video length mismatch is already surfaced separately as a
    warning by VideoAssemblyService before this command ever runs; this
    function's job is only to avoid making that mismatch worse by cutting
    content out during the mux itself.
    """
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        str(output_path),
    ]
