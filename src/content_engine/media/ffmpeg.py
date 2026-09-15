"""Thin FFmpeg/ffprobe subprocess boundary.

This is the only module in the codebase that imports ``subprocess``. All
FFmpeg/ffprobe invocation, binary-availability checking, and media probing
live here. Command *construction* lives in ``media/assembly.py`` — this
module only knows how to run an already-built argument list and interpret
its result; it never builds a filter graph or decides what to run.

Commands are always invoked as an argument list with ``shell=False``,
never as an interpolated shell string (ARCHITECTURE §21).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class FFmpegExecutionError(Exception):
    """Raised when an ffmpeg/ffprobe invocation fails or produces unusable output."""


class FFmpegRunner:
    """Executes ffmpeg/ffprobe commands and translates failures explicitly.

    Injectable so callers (and tests) can substitute a fake implementation
    without invoking a real subprocess.
    """

    def run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """Run an ffmpeg/ffprobe command, raising on non-zero exit.

        Args:
            args: Full command as a list (e.g. ``["ffmpeg", "-y", "-i", ...]``).
                Never a shell string.

        Returns:
            The completed process, on success.

        Raises:
            FFmpegExecutionError: If the process exits non-zero. The message
                includes the command and the process's own stderr, so the
                real diagnostic is never swallowed.
        """
        result = subprocess.run(args, shell=False, capture_output=True, text=True)
        if result.returncode != 0:
            raise FFmpegExecutionError(
                f"{args[0]} failed (exit code {result.returncode}): {' '.join(args)}\n"
                f"stderr: {result.stderr.strip()}"
            )
        return result

    def is_ffmpeg_available(self) -> bool:
        """Return True if the ``ffmpeg`` binary is available on PATH."""
        return shutil.which("ffmpeg") is not None

    def is_ffprobe_available(self) -> bool:
        """Return True if the ``ffprobe`` binary is available on PATH."""
        return shutil.which("ffprobe") is not None

    def probe_duration(self, path: Path) -> float:
        """Return a media file's duration in seconds via ffprobe.

        Raises:
            FFmpegExecutionError: If ffprobe fails or its output can't be parsed.
        """
        result = self.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ]
        )
        try:
            data = json.loads(result.stdout)
            return float(data["format"]["duration"])
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            raise FFmpegExecutionError(
                f"Could not parse ffprobe duration output for {path}: {exc}"
            ) from exc

    def probe_dimensions(self, path: Path) -> tuple[int, int]:
        """Return (width, height) of a media file's first video stream via ffprobe.

        Raises:
            FFmpegExecutionError: If ffprobe fails or its output can't be parsed.
        """
        result = self.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "json",
                str(path),
            ]
        )
        try:
            data = json.loads(result.stdout)
            stream = data["streams"][0]
            return int(stream["width"]), int(stream["height"])
        except (KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
            raise FFmpegExecutionError(
                f"Could not parse ffprobe dimensions output for {path}: {exc}"
            ) from exc
