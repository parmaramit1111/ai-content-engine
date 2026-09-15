"""Unit tests for the FFmpegRunner subprocess boundary.

Covers: successful execution, non-zero exit, stderr preservation,
missing ffmpeg/ffprobe, duration probing, resolution probing,
shell=False, and list-based subprocess arguments. All subprocess calls
are monkeypatched — no real ffmpeg is invoked.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from content_engine.media.ffmpeg import FFmpegExecutionError, FFmpegRunner


def _completed_process(
    args: list[str], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=args, returncode=returncode, stdout=stdout, stderr=stderr
    )


class TestFFmpegRunnerRun:
    def test_successful_execution_returns_completed_process(self):
        runner = FFmpegRunner()
        with patch("subprocess.run", return_value=_completed_process(["ffmpeg"])) as mock_run:
            result = runner.run(["ffmpeg", "-y", "-i", "in.mp4", "out.mp4"])

        assert result.returncode == 0
        mock_run.assert_called_once()

    def test_uses_list_arguments_and_shell_false(self):
        runner = FFmpegRunner()
        args = ["ffmpeg", "-y", "-i", "in.mp4", "out.mp4"]
        with patch("subprocess.run", return_value=_completed_process(args)) as mock_run:
            runner.run(args)

        call_args, call_kwargs = mock_run.call_args
        assert call_args[0] == args
        assert isinstance(call_args[0], list)
        assert call_kwargs["shell"] is False

    def test_non_zero_exit_raises_with_stderr_preserved(self):
        runner = FFmpegRunner()
        failure = _completed_process(
            ["ffmpeg"], returncode=1, stderr="Unknown encoder 'bogus'"
        )
        with (
            patch("subprocess.run", return_value=failure),
            pytest.raises(FFmpegExecutionError, match="Unknown encoder 'bogus'"),
        ):
            runner.run(["ffmpeg", "-c:v", "bogus", "out.mp4"])

    def test_error_message_includes_exit_code_and_command(self):
        runner = FFmpegRunner()
        failure = _completed_process(["ffmpeg"], returncode=2, stderr="boom")
        with (
            patch("subprocess.run", return_value=failure),
            pytest.raises(FFmpegExecutionError, match="exit code 2"),
        ):
            runner.run(["ffmpeg", "-i", "in.mp4"])


class TestFFmpegAvailability:
    def test_ffmpeg_available(self):
        runner = FFmpegRunner()
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            assert runner.is_ffmpeg_available() is True

    def test_ffmpeg_missing(self):
        runner = FFmpegRunner()
        with patch("shutil.which", return_value=None):
            assert runner.is_ffmpeg_available() is False

    def test_ffprobe_available(self):
        runner = FFmpegRunner()
        with patch("shutil.which", return_value="/usr/bin/ffprobe"):
            assert runner.is_ffprobe_available() is True

    def test_ffprobe_missing(self):
        runner = FFmpegRunner()
        with patch("shutil.which", return_value=None):
            assert runner.is_ffprobe_available() is False


class TestProbeDuration:
    def test_parses_duration_from_ffprobe_json(self):
        runner = FFmpegRunner()
        stdout = json.dumps({"format": {"duration": "45.123"}})
        with patch("subprocess.run", return_value=_completed_process(["ffprobe"], stdout=stdout)):
            duration = runner.probe_duration(Path("/clip.mp4"))

        assert duration == pytest.approx(45.123)

    def test_uses_ffprobe_binary_and_json_output(self):
        runner = FFmpegRunner()
        stdout = json.dumps({"format": {"duration": "1.0"}})
        with patch(
            "subprocess.run", return_value=_completed_process(["ffprobe"], stdout=stdout)
        ) as mock_run:
            runner.probe_duration(Path("/clip.mp4"))

        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "ffprobe"
        assert "-of" in call_args
        assert "json" in call_args
        assert str(Path("/clip.mp4")) in call_args

    def test_malformed_output_raises_actionable_error(self):
        runner = FFmpegRunner()
        with patch(
            "subprocess.run", return_value=_completed_process(["ffprobe"], stdout="not json")
        ), pytest.raises(FFmpegExecutionError, match="Could not parse ffprobe"):
            runner.probe_duration(Path("/clip.mp4"))

    def test_ffprobe_failure_propagates_as_execution_error(self):
        runner = FFmpegRunner()
        failure = _completed_process(["ffprobe"], returncode=1, stderr="No such file")
        with (
            patch("subprocess.run", return_value=failure),
            pytest.raises(FFmpegExecutionError, match="No such file"),
        ):
            runner.probe_duration(Path("/missing.mp4"))


class TestProbeDimensions:
    def test_parses_dimensions_from_ffprobe_json(self):
        runner = FFmpegRunner()
        stdout = json.dumps({"streams": [{"width": 1080, "height": 1920}]})
        with patch("subprocess.run", return_value=_completed_process(["ffprobe"], stdout=stdout)):
            width, height = runner.probe_dimensions(Path("/clip.mp4"))

        assert (width, height) == (1080, 1920)

    def test_selects_first_video_stream(self):
        runner = FFmpegRunner()
        stdout = json.dumps({"streams": [{"width": 640, "height": 360}]})
        with patch(
            "subprocess.run", return_value=_completed_process(["ffprobe"], stdout=stdout)
        ) as mock_run:
            runner.probe_dimensions(Path("/clip.mp4"))

        call_args = mock_run.call_args[0][0]
        assert "-select_streams" in call_args
        assert "v:0" in call_args

    def test_malformed_output_raises_actionable_error(self):
        runner = FFmpegRunner()
        with patch(
            "subprocess.run", return_value=_completed_process(["ffprobe"], stdout="{}")
        ), pytest.raises(FFmpegExecutionError, match="Could not parse ffprobe"):
            runner.probe_dimensions(Path("/clip.mp4"))
