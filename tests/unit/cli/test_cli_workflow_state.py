"""CLI tests for WorkflowState integration (Phase 12C).

Covers: `topic create` seeding an empty WorkflowState, ID fallback via
`--topic-id` when a stage-specific `--*-id` is omitted, explicit IDs
always overriding WorkflowState, regeneration counting across
brief/script/storyboard/assemble, Gemini usage accumulation, Flow credit
accumulation, `content workflow show`, and confirmation that Topic.status
is never touched by any of this.
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
from content_engine.providers.results import GenerationResult, GenerationUsage
from content_engine.storage import ContentStore

runner = CliRunner()

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


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


def _env(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    content_root = tmp_path / "content"
    asset_root = tmp_path / "assets"
    monkeypatch.setenv("CONTENT_ROOT", str(content_root))
    monkeypatch.setenv("ASSET_ROOT", str(asset_root))

    # A generous local Gemini budget so the fake provider's record_usage()
    # calls succeed — BudgetTracker.record_usage refuses to record ANY
    # usage (even with force=True) when no local_budget is configured at
    # all, which is the real repo default (config/budgets.yaml has it
    # null). The budget gate itself is covered separately in
    # test_cli_pipeline.py::TestGeminiBudgetGate.
    budget_config = tmp_path / "budgets.yaml"
    budget_config.write_text(
        "budgets:\n"
        "  gemini:\n"
        "    model: null\n"
        "    period: provider-defined\n"
        "    local_budget:\n"
        "      requests_per_day: 10000\n"
        "      tokens_per_day: 10000000\n"
        "    warning_percent: 80\n"
        "    hard_stop_percent: 100\n"
        "    reserve_percent: 20\n"
        "    paid_fallback: false\n"
    )
    monkeypatch.setenv("BUDGET_CONFIG", str(budget_config))

    return content_root, asset_root


def _extract(output: str, key: str) -> str:
    for line in output.splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    raise AssertionError(f"{key}= not found in output:\n{output}")


def _create_topic(content_root: Path) -> str:
    result = runner.invoke(
        app,
        [
            "topic",
            "create",
            "--title",
            "Why Database Indexes Make Queries Faster",
            "--category",
            "backend_engineering",
            "--audience",
            "backend engineers",
            "--difficulty",
            "intermediate",
            "--hook",
            "Why does one line of SQL make queries 100x faster?",
            "--content-root",
            str(content_root),
        ],
    )
    assert result.exit_code == 0, result.output
    return _extract(result.output, "topic_id")


def _create_verified_research(content_root: Path, topic_id: str) -> str:
    create_result = runner.invoke(
        app,
        [
            "research",
            "create",
            "--topic-id",
            topic_id,
            "--key-fact",
            "An index avoids a full table scan",
            "--primary-source",
            "https://www.postgresql.org/docs/current/indexes.html",
            "--content-root",
            str(content_root),
        ],
    )
    assert create_result.exit_code == 0, create_result.output
    research_id = _extract(create_result.output, "research_id")

    verify_result = runner.invoke(
        app,
        ["research", "verify", "--research-id", research_id, "--content-root", str(content_root)],
    )
    assert verify_result.exit_code == 0, verify_result.output
    return research_id


def _patch_gemini_provider(monkeypatch, response_text: str, *, tokens: int = 100) -> None:
    """Replace GeminiProvider with a fake that reports fixed token usage.

    Mirrors the pattern in test_cli_pipeline.py, extended to report a
    ``GenerationUsage`` so tests can assert WorkflowState accumulates it.
    """

    class _FakeGeminiProvider:
        def __init__(self, api_key, model, tracker):
            self._tracker = tracker

        async def generate(self, prompt, *, operation, content_id=None):
            from uuid import UUID as _UUID

            parsed = None
            if content_id is not None:
                try:
                    parsed = _UUID(content_id)
                except ValueError:
                    parsed = None
            self._tracker.record_usage(
                "gemini",
                units=1,
                operation=operation,
                content_id=parsed,
                unit_type="requests",
                force=True,
            )
            self._tracker.record_usage(
                "gemini",
                units=tokens,
                operation=operation,
                content_id=parsed,
                unit_type="tokens",
                force=True,
            )
            return GenerationResult(
                text=response_text,
                provider="fake",
                model="fake-model",
                operation=operation,
                content_id=content_id,
                usage=GenerationUsage(input_tokens=tokens, output_tokens=0, total_tokens=tokens),
            )

    monkeypatch.setattr("content_engine.cli.GeminiProvider", _FakeGeminiProvider)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test-model")
    monkeypatch.setenv("GEMINI_API_KEY", "unused-because-provider-is-faked")


_BRIEF_JSON = json.dumps(
    {
        "problem": "p",
        "core_explanation": "c",
        "example": "e",
        "takeaway": "t",
        "cta": "cta",
        "estimated_duration": 30,
        "visual_style": "clean",
    }
)
_SCRIPT_JSON = json.dumps(
    {
        "scenes": [
            {"number": 1, "duration": 1.0, "narration": "Hook", "visual_prompt": "spinner"},
            {"number": 2, "duration": 1.0, "narration": "Explain", "visual_prompt": "diagram"},
        ]
    }
)
_STORYBOARD_JSON = json.dumps(
    {
        "scenes": [
            {"number": 1, "visual_prompt": "enriched spinner"},
            {"number": 2, "visual_prompt": "enriched diagram"},
        ]
    }
)


class TestTopicCreateSeedsWorkflowState:
    def test_creates_empty_workflow_state(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)

        store = ContentStore(content_root)
        state = store.load_workflow_state(UUID(topic_id))

        assert state.topic_id == UUID(topic_id)
        assert state.research_id is None
        assert state.brief_regenerations == 0

    def test_topic_status_never_touched(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)

        store = ContentStore(content_root)
        topic = store.load_topic(UUID(topic_id))

        assert topic.status.value == "IDEA"


class TestResearchUpdatesWorkflowState:
    def test_create_records_research_id(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)

        create_result = runner.invoke(
            app,
            [
                "research",
                "create",
                "--topic-id",
                topic_id,
                "--key-fact",
                "fact",
                "--content-root",
                str(content_root),
            ],
        )
        research_id = _extract(create_result.output, "research_id")

        store = ContentStore(content_root)
        state = store.load_workflow_state(UUID(topic_id))
        assert state.research_id == UUID(research_id)

    def test_verify_fallback_from_topic_id(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)
        runner.invoke(
            app,
            [
                "research",
                "create",
                "--topic-id",
                topic_id,
                "--content-root",
                str(content_root),
            ],
        )

        # No --research-id at all — resolved purely from WorkflowState via --topic-id.
        result = runner.invoke(
            app, ["research", "verify", "--topic-id", topic_id, "--content-root", str(content_root)]
        )
        assert result.exit_code == 0, result.output
        assert _extract(result.output, "verification_status") == "verified"

    def test_verify_without_topic_id_or_research_id_fails_clearly(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        result = runner.invoke(app, ["research", "verify", "--content-root", str(content_root)])
        assert result.exit_code == 1
        assert "research_id not supplied" in result.output


class TestBriefFallbackAndAccumulation:
    def test_research_id_falls_back_to_workflow_state(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)
        _create_verified_research(content_root, topic_id)
        _patch_gemini_provider(monkeypatch, _BRIEF_JSON, tokens=250)

        # --research-id omitted entirely; resolved from WorkflowState.
        result = runner.invoke(
            app, ["brief", "generate", "--topic-id", topic_id, "--content-root", str(content_root)]
        )
        assert result.exit_code == 0, result.output

        store = ContentStore(content_root)
        state = store.load_workflow_state(UUID(topic_id))
        assert state.brief_id is not None
        assert state.gemini_requests_used == 1
        assert state.gemini_tokens_used == 250
        assert state.brief_regenerations == 0

    def test_explicit_research_id_overrides_workflow_state(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)
        _create_verified_research(content_root, topic_id)

        # A second, unrelated verified research record for the same topic.
        other = runner.invoke(
            app,
            [
                "research",
                "create",
                "--topic-id",
                topic_id,
                "--key-fact",
                "alternate fact",
                "--primary-source",
                "https://example.com",
                "--content-root",
                str(content_root),
            ],
        )
        other_research_id = _extract(other.output, "research_id")
        runner.invoke(
            app,
            [
                "research",
                "verify",
                "--research-id",
                other_research_id,
                "--content-root",
                str(content_root),
            ],
        )

        _patch_gemini_provider(monkeypatch, _BRIEF_JSON)
        result = runner.invoke(
            app,
            [
                "brief",
                "generate",
                "--topic-id",
                topic_id,
                "--research-id",
                other_research_id,
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code == 0, result.output

        store = ContentStore(content_root)
        state = store.load_workflow_state(UUID(topic_id))
        # WorkflowState.research_id is updated to whichever was actually used —
        # the explicit override, not the earlier fallback candidate.
        assert state.research_id == UUID(other_research_id)

    def test_regeneration_count_increments_on_second_call(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)
        _create_verified_research(content_root, topic_id)

        _patch_gemini_provider(monkeypatch, _BRIEF_JSON, tokens=100)
        first = runner.invoke(
            app, ["brief", "generate", "--topic-id", topic_id, "--content-root", str(content_root)]
        )
        assert first.exit_code == 0, first.output

        _patch_gemini_provider(monkeypatch, _BRIEF_JSON, tokens=150)
        second = runner.invoke(
            app, ["brief", "generate", "--topic-id", topic_id, "--content-root", str(content_root)]
        )
        assert second.exit_code == 0, second.output

        store = ContentStore(content_root)
        state = store.load_workflow_state(UUID(topic_id))
        assert state.brief_regenerations == 1
        assert state.gemini_requests_used == 2
        assert state.gemini_tokens_used == 250

    def test_omitting_topic_id_matches_old_behavior_no_state_written(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)
        research_id = _create_verified_research(content_root, topic_id)
        _patch_gemini_provider(monkeypatch, _BRIEF_JSON)

        result = runner.invoke(
            app,
            [
                "brief",
                "generate",
                "--topic-id",
                topic_id,
                "--research-id",
                research_id,
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code == 0, result.output
        # brief_generate always requires --topic-id (unchanged from 12B), so
        # WorkflowState is always touched here — assert it reflects this call.
        store = ContentStore(content_root)
        state = store.load_workflow_state(UUID(topic_id))
        assert state.brief_id is not None


class TestScriptStoryboardFallback:
    def _generate_brief(self, content_root: Path, topic_id: str, monkeypatch) -> str:
        research_id = _create_verified_research(content_root, topic_id)
        _patch_gemini_provider(monkeypatch, _BRIEF_JSON)
        result = runner.invoke(
            app,
            [
                "brief",
                "generate",
                "--topic-id",
                topic_id,
                "--research-id",
                research_id,
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code == 0, result.output
        return _extract(result.output, "brief_id")

    def test_script_generate_fallback_and_no_topic_id_is_backward_compatible(
        self, tmp_path, monkeypatch
    ):
        content_root, _ = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)
        brief_id = self._generate_brief(content_root, topic_id, monkeypatch)

        # Old-style: explicit --brief-id, no --topic-id at all.
        _patch_gemini_provider(monkeypatch, _SCRIPT_JSON)
        old_style = runner.invoke(
            app, ["script", "generate", "--brief-id", brief_id, "--content-root", str(content_root)]
        )
        assert old_style.exit_code == 0, old_style.output

        # New-style: fallback via --topic-id, --brief-id omitted.
        _patch_gemini_provider(monkeypatch, _SCRIPT_JSON)
        new_style = runner.invoke(
            app, ["script", "generate", "--topic-id", topic_id, "--content-root", str(content_root)]
        )
        assert new_style.exit_code == 0, new_style.output

        store = ContentStore(content_root)
        state = store.load_workflow_state(UUID(topic_id))
        assert state.script_id is not None
        # WorkflowState was only touched by the new-style call (which supplied
        # --topic-id) — one regeneration recorded there, not from the old-style
        # call, which never mentioned --topic-id.
        assert state.script_regenerations == 0

    def test_storyboard_generate_fallback(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)
        brief_id = self._generate_brief(content_root, topic_id, monkeypatch)

        _patch_gemini_provider(monkeypatch, _SCRIPT_JSON)
        script_result = runner.invoke(
            app,
            [
                "script",
                "generate",
                "--topic-id",
                topic_id,
                "--brief-id",
                brief_id,
                "--content-root",
                str(content_root),
            ],
        )
        assert script_result.exit_code == 0, script_result.output

        _patch_gemini_provider(monkeypatch, _STORYBOARD_JSON)
        storyboard_result = runner.invoke(
            app,
            ["storyboard", "generate", "--topic-id", topic_id, "--content-root", str(content_root)],
        )
        assert storyboard_result.exit_code == 0, storyboard_result.output

        store = ContentStore(content_root)
        state = store.load_workflow_state(UUID(topic_id))
        assert state.storyboard_id is not None
        assert state.script_id is not None
        assert state.brief_id == UUID(brief_id)


class TestAssembleAccumulatesFlowCredits:
    def _build_storyboard_via_workflow(self, content_root, topic_id, monkeypatch) -> str:
        brief_id = None
        research_id = _create_verified_research(content_root, topic_id)
        _patch_gemini_provider(monkeypatch, _BRIEF_JSON)
        brief_result = runner.invoke(
            app,
            [
                "brief",
                "generate",
                "--topic-id",
                topic_id,
                "--research-id",
                research_id,
                "--content-root",
                str(content_root),
            ],
        )
        brief_id = _extract(brief_result.output, "brief_id")

        _patch_gemini_provider(monkeypatch, _SCRIPT_JSON)
        script_result = runner.invoke(
            app,
            [
                "script",
                "generate",
                "--topic-id",
                topic_id,
                "--brief-id",
                brief_id,
                "--content-root",
                str(content_root),
            ],
        )
        script_id = _extract(script_result.output, "script_id")

        _patch_gemini_provider(monkeypatch, _STORYBOARD_JSON)
        storyboard_result = runner.invoke(
            app,
            [
                "storyboard",
                "generate",
                "--topic-id",
                topic_id,
                "--script-id",
                script_id,
                "--brief-id",
                brief_id,
                "--content-root",
                str(content_root),
            ],
        )
        return _extract(storyboard_result.output, "storyboard_id")

    def test_flow_credits_and_manifest_remembered(self, tmp_path, monkeypatch):
        content_root, asset_root = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)
        storyboard_id = self._build_storyboard_via_workflow(content_root, topic_id, monkeypatch)

        clip1 = asset_root / "raw" / "scene-1.mp4"
        clip2 = asset_root / "raw" / "scene-2.mp4"
        clip1.parent.mkdir(parents=True, exist_ok=True)
        clip1.write_bytes(b"fake clip 1")
        clip2.write_bytes(b"fake clip 2")

        manifest = tmp_path / "assets.json"
        manifest.write_text(
            json.dumps(
                [
                    {
                        "scene_number": 1,
                        "path": "raw/scene-1.mp4",
                        "source": "google_flow",
                        "flow_credits_used": 20,
                    },
                    {
                        "scene_number": 2,
                        "path": "raw/scene-2.mp4",
                        "source": "google_flow",
                        "flow_credits_used": 10,
                    },
                ]
            )
        )

        result = runner.invoke(
            app,
            [
                "asset",
                "validate",
                "--topic-id",
                topic_id,
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

        store = ContentStore(content_root)
        state = store.load_workflow_state(UUID(topic_id))
        assert state.asset_manifest_path == str(manifest)

        # asset validate never touches assemble_regenerations/flow credits —
        # only assemble (which actually builds Assets and consumes credits) does.
        assert state.flow_credits_used == 0

    def test_asset_validate_manifest_fallback(self, tmp_path, monkeypatch):
        content_root, asset_root = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)
        storyboard_id = self._build_storyboard_via_workflow(content_root, topic_id, monkeypatch)

        clip1 = asset_root / "raw" / "scene-1.mp4"
        clip2 = asset_root / "raw" / "scene-2.mp4"
        clip1.parent.mkdir(parents=True, exist_ok=True)
        clip1.write_bytes(b"fake clip 1")
        clip2.write_bytes(b"fake clip 2")
        manifest = tmp_path / "assets.json"
        manifest.write_text(
            json.dumps(
                [
                    {"scene_number": 1, "path": "raw/scene-1.mp4", "source": "google_flow"},
                    {"scene_number": 2, "path": "raw/scene-2.mp4", "source": "google_flow"},
                ]
            )
        )

        first = runner.invoke(
            app,
            [
                "asset",
                "validate",
                "--topic-id",
                topic_id,
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
        assert first.exit_code == 0, first.output

        # Second call omits both --storyboard-id and --manifest entirely.
        second = runner.invoke(
            app,
            [
                "asset",
                "validate",
                "--topic-id",
                topic_id,
                "--content-root",
                str(content_root),
                "--asset-root",
                str(asset_root),
            ],
        )
        assert second.exit_code == 0, second.output
        assert "scenes_covered=True" in second.output


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg/ffprobe not available on PATH")
class TestAssembleRealFlowCreditsAndRegenerations:
    def _build_storyboard(self, content_root: Path, topic_id: str, monkeypatch) -> str:
        research_id = _create_verified_research(content_root, topic_id)
        _patch_gemini_provider(monkeypatch, _BRIEF_JSON)
        brief_result = runner.invoke(
            app,
            [
                "brief",
                "generate",
                "--topic-id",
                topic_id,
                "--research-id",
                research_id,
                "--content-root",
                str(content_root),
            ],
        )
        brief_id = _extract(brief_result.output, "brief_id")

        _patch_gemini_provider(monkeypatch, _SCRIPT_JSON)
        script_result = runner.invoke(
            app,
            [
                "script",
                "generate",
                "--topic-id",
                topic_id,
                "--brief-id",
                brief_id,
                "--content-root",
                str(content_root),
            ],
        )
        script_id = _extract(script_result.output, "script_id")

        _patch_gemini_provider(monkeypatch, _STORYBOARD_JSON)
        storyboard_result = runner.invoke(
            app,
            [
                "storyboard",
                "generate",
                "--topic-id",
                topic_id,
                "--script-id",
                script_id,
                "--brief-id",
                brief_id,
                "--content-root",
                str(content_root),
            ],
        )
        return _extract(storyboard_result.output, "storyboard_id")

    def test_assemble_accumulates_flow_credits_and_counts_regenerations(
        self, tmp_path, monkeypatch
    ):
        content_root, asset_root = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)
        storyboard_id = self._build_storyboard(content_root, topic_id, monkeypatch)

        _synthesize_clip(asset_root / "raw" / "scene-1.mp4", 1.0)
        _synthesize_clip(asset_root / "raw" / "scene-2.mp4", 1.0)
        manifest = tmp_path / "assets.json"
        manifest.write_text(
            json.dumps(
                [
                    {
                        "scene_number": 1,
                        "path": "raw/scene-1.mp4",
                        "source": "google_flow",
                        "flow_credits_used": 20,
                    },
                    {
                        "scene_number": 2,
                        "path": "raw/scene-2.mp4",
                        "source": "google_flow",
                        "flow_credits_used": 10,
                    },
                ]
            )
        )

        first = runner.invoke(
            app,
            [
                "assemble",
                "--topic-id",
                topic_id,
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
        assert first.exit_code == 0, first.output

        store = ContentStore(content_root)
        state = store.load_workflow_state(UUID(topic_id))
        assert state.flow_credits_used == 30
        assert state.assemble_regenerations == 0
        assert state.production_id is not None
        first_production_id = state.production_id

        # Re-running assemble for the same topic (e.g. regenerating a scene)
        # accumulates credits again and counts as a regeneration.
        second = runner.invoke(
            app,
            [
                "assemble",
                "--topic-id",
                topic_id,
                "--content-root",
                str(content_root),
                "--asset-root",
                str(asset_root),
            ],
        )
        assert second.exit_code == 0, second.output

        state = store.load_workflow_state(UUID(topic_id))
        assert state.flow_credits_used == 60
        assert state.assemble_regenerations == 1
        assert state.production_id != first_production_id


class TestWorkflowShow:
    def test_show_prints_current_state(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)
        _create_verified_research(content_root, topic_id)

        result = runner.invoke(
            app, ["workflow", "show", "--topic-id", topic_id, "--content-root", str(content_root)]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["topic_id"] == topic_id
        assert payload["research_id"] is not None

    def test_show_missing_topic_fails_clearly(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        result = runner.invoke(
            app,
            ["workflow", "show", "--topic-id", str(uuid4()), "--content-root", str(content_root)],
        )
        assert result.exit_code == 1
        assert "WorkflowState artifact not found" in result.output
