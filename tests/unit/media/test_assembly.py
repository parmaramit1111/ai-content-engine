"""Unit tests for FFmpeg command construction (pure — no subprocess invoked).

Covers: exact argument construction, target resolution, scale/pad
behavior, concat command, audio mux command, path handling, list
arguments, and that no subprocess call happens anywhere in this module.
"""

from pathlib import Path
from unittest.mock import patch

from content_engine.media.assembly import (
    AUDIO_CHANNELS,
    AUDIO_CODEC,
    AUDIO_SAMPLE_RATE,
    PIXEL_FORMAT,
    TARGET_FRAME_RATE,
    TARGET_HEIGHT,
    TARGET_WIDTH,
    VIDEO_CODEC,
    build_concat_args,
    build_concat_list_content,
    build_mux_audio_args,
    build_scale_pad_args,
)


class TestTargetResolution:
    def test_target_is_9_16_vertical(self):
        assert TARGET_HEIGHT > TARGET_WIDTH
        assert (TARGET_WIDTH, TARGET_HEIGHT) == (1080, 1920)


class TestBuildScalePadArgs:
    def test_returns_list_of_strings(self):
        args = build_scale_pad_args(Path("/in/clip.mp4"), Path("/out/clip.mp4"))
        assert isinstance(args, list)
        assert all(isinstance(a, str) for a in args)

    def test_includes_input_and_output_paths(self):
        args = build_scale_pad_args(Path("/in/clip.mp4"), Path("/out/clip.mp4"))
        assert "/in/clip.mp4" in args
        assert args[-1] == "/out/clip.mp4"

    def test_scale_filter_uses_target_dimensions(self):
        args = build_scale_pad_args(Path("/in/clip.mp4"), Path("/out/clip.mp4"))
        vf_index = args.index("-vf")
        filter_expr = args[vf_index + 1]
        assert f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}" in filter_expr
        assert f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}" in filter_expr

    def test_scale_filter_forces_deterministic_frame_rate(self):
        args = build_scale_pad_args(Path("/in/clip.mp4"), Path("/out/clip.mp4"))
        filter_expr = args[args.index("-vf") + 1]
        assert f"fps={TARGET_FRAME_RATE}" in filter_expr

    def test_overwrite_flag_present(self):
        args = build_scale_pad_args(Path("/in/clip.mp4"), Path("/out/clip.mp4"))
        assert "-y" in args

    def test_starts_with_ffmpeg(self):
        args = build_scale_pad_args(Path("/in/clip.mp4"), Path("/out/clip.mp4"))
        assert args[0] == "ffmpeg"

    def test_pins_explicit_video_codec_and_pixel_format(self):
        """Fix 1: normalization must fix codec/pixel format, not just dimensions,
        so the later concat-demuxer stream-copy step has uniform inputs."""
        args = build_scale_pad_args(Path("/in/clip.mp4"), Path("/out/clip.mp4"))
        assert "-c:v" in args
        assert args[args.index("-c:v") + 1] == VIDEO_CODEC == "libx264"
        assert "-pix_fmt" in args
        assert args[args.index("-pix_fmt") + 1] == PIXEL_FORMAT == "yuv420p"

    def test_pins_explicit_deterministic_audio_normalization(self):
        """Fix 1: source audio must never be blindly copied (-c:a copy) —
        it must be normalized to a fixed codec/sample-rate/channel layout."""
        args = build_scale_pad_args(Path("/in/clip.mp4"), Path("/out/clip.mp4"))
        assert "-c:a" in args
        assert args[args.index("-c:a") + 1] == AUDIO_CODEC == "aac"
        assert "-ar" in args
        assert args[args.index("-ar") + 1] == str(AUDIO_SAMPLE_RATE) == "48000"
        assert "-ac" in args
        assert args[args.index("-ac") + 1] == str(AUDIO_CHANNELS) == "2"

    def test_does_not_blindly_copy_audio(self):
        args = build_scale_pad_args(Path("/in/clip.mp4"), Path("/out/clip.mp4"))
        c_a_index = args.index("-c:a")
        assert args[c_a_index + 1] != "copy"


class TestBuildConcatListContent:
    def test_one_file_per_line(self):
        content = build_concat_list_content([Path("/a.mp4"), Path("/b.mp4")])
        assert content == "file '/a.mp4'\nfile '/b.mp4'\n"

    def test_preserves_order(self):
        content = build_concat_list_content([Path("/scene-2.mp4"), Path("/scene-1.mp4")])
        lines = content.strip().split("\n")
        assert lines[0] == "file '/scene-2.mp4'"
        assert lines[1] == "file '/scene-1.mp4'"

    def test_empty_list_returns_empty_string(self):
        assert build_concat_list_content([]) == ""

    def test_escapes_single_quotes_in_path(self):
        content = build_concat_list_content([Path("/a/it's-a-clip.mp4")])
        assert "it'\\''s-a-clip.mp4" in content


class TestBuildConcatArgs:
    def test_returns_list_of_strings(self):
        args = build_concat_args(Path("/work/list.txt"), Path("/out/concat.mp4"))
        assert isinstance(args, list)
        assert all(isinstance(a, str) for a in args)

    def test_uses_concat_demuxer(self):
        args = build_concat_args(Path("/work/list.txt"), Path("/out/concat.mp4"))
        assert "-f" in args
        assert args[args.index("-f") + 1] == "concat"
        assert "-safe" in args
        assert args[args.index("-safe") + 1] == "0"

    def test_includes_list_and_output_paths(self):
        args = build_concat_args(Path("/work/list.txt"), Path("/out/concat.mp4"))
        assert "/work/list.txt" in args
        assert args[-1] == "/out/concat.mp4"


class TestBuildMuxAudioArgs:
    def test_returns_list_of_strings(self):
        args = build_mux_audio_args(Path("/v.mp4"), Path("/a.mp3"), Path("/out.mp4"))
        assert isinstance(args, list)
        assert all(isinstance(a, str) for a in args)

    def test_includes_video_and_audio_inputs(self):
        args = build_mux_audio_args(Path("/v.mp4"), Path("/a.mp3"), Path("/out.mp4"))
        assert "/v.mp4" in args
        assert "/a.mp3" in args
        assert args[-1] == "/out.mp4"

    def test_maps_video_and_audio_streams_explicitly(self):
        args = build_mux_audio_args(Path("/v.mp4"), Path("/a.mp3"), Path("/out.mp4"))
        assert "-map" in args
        assert "0:v:0" in args
        assert "1:a:0" in args

    def test_does_not_use_shortest_flag(self):
        """Fix 4: -shortest silently truncates whichever stream is longer
        (most commonly cutting off narration audio longer than the video).
        Neither stream should be silently cut short during mux."""
        args = build_mux_audio_args(Path("/v.mp4"), Path("/a.mp3"), Path("/out.mp4"))
        assert "-shortest" not in args


class TestNoSubprocessInvoked:
    def test_command_construction_never_calls_subprocess(self):
        with patch("subprocess.run") as mock_run:
            build_scale_pad_args(Path("/in.mp4"), Path("/out.mp4"))
            build_concat_args(Path("/list.txt"), Path("/out.mp4"))
            build_mux_audio_args(Path("/v.mp4"), Path("/a.mp3"), Path("/out.mp4"))
            build_concat_list_content([Path("/a.mp4")])

        mock_run.assert_not_called()

    def test_module_does_not_import_subprocess(self):
        import ast
        import inspect

        import content_engine.media.assembly as assembly_module

        tree = ast.parse(inspect.getsource(assembly_module))
        imported_names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported_names.append(node.module or "")

        assert "subprocess" not in imported_names
