"""CLI tests for the topic -> research -> brief -> script -> storyboard pipeline.

Gemini-backed commands (brief/script/storyboard generate) patch
``content_engine.cli.GeminiProvider`` with a fake so no real network calls
are made, matching the repository-wide provider-mocking convention. One
test uses the real ``GeminiProvider`` (with ``genai.Client`` patched, per
``tests/unit/providers/test_gemini_provider.py`` convention) to prove the
budget hard-stop gate is never bypassed by the CLI.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from typer.testing import CliRunner

from content_engine.cli import app
from content_engine.providers.results import GenerationResult
from content_engine.storage import ContentStore

runner = CliRunner()


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


def _patch_gemini_provider(monkeypatch, response_text: str) -> list[dict]:
    """Replace GeminiProvider with a fake so no network call is ever made."""
    calls: list[dict] = []

    class _FakeGeminiProvider:
        def __init__(self, api_key, model, tracker):
            self._api_key = api_key
            self._model = model
            self._tracker = tracker

        async def generate(self, prompt, *, operation, content_id=None):
            calls.append({"prompt": prompt, "operation": operation, "content_id": content_id})
            return GenerationResult(
                text=response_text,
                provider="fake",
                model="fake-model",
                operation=operation,
                content_id=content_id,
            )

    monkeypatch.setattr("content_engine.cli.GeminiProvider", _FakeGeminiProvider)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test-model")
    monkeypatch.setenv("GEMINI_API_KEY", "unused-because-provider-is-faked")
    return calls


class TestTopicCreate:
    def test_creates_and_persists(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)

        store = ContentStore(content_root)
        topic = store.load_topic(UUID(topic_id))
        assert topic.title == "Why Database Indexes Make Queries Faster"
        assert topic.category.value == "backend_engineering"

    def test_invalid_category_rejected(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        result = runner.invoke(
            app,
            [
                "topic",
                "create",
                "--title",
                "x",
                "--category",
                "not_a_category",
                "--audience",
                "a",
                "--difficulty",
                "beginner",
                "--hook",
                "h",
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code != 0


class TestResearchCreateAndVerify:
    def test_create_starts_unverified(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)

        result = runner.invoke(
            app,
            [
                "research",
                "create",
                "--topic-id",
                topic_id,
                "--key-fact",
                "fact one",
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code == 0, result.output
        assert _extract(result.output, "verification_status") == "unverified"

    def test_verify_marks_verified_and_ready(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)
        research_id = _create_verified_research(content_root, topic_id)

        store = ContentStore(content_root)
        research = store.load_research_notes(UUID(research_id))
        assert research.verification_status.value == "verified"

    def test_verify_reports_not_ready_without_facts(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)
        create_result = runner.invoke(
            app, ["research", "create", "--topic-id", topic_id, "--content-root", str(content_root)]
        )
        research_id = _extract(create_result.output, "research_id")

        verify_result = runner.invoke(
            app,
            [
                "research",
                "verify",
                "--research-id",
                research_id,
                "--content-root",
                str(content_root),
            ],
        )
        assert verify_result.exit_code == 0, verify_result.output
        assert _extract(verify_result.output, "ready_for_brief") == "False"

    def test_create_missing_topic_fails(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        result = runner.invoke(
            app,
            ["research", "create", "--topic-id", str(uuid4()), "--content-root", str(content_root)],
        )
        assert result.exit_code == 1
        assert "Topic artifact not found" in result.output

    def test_verify_missing_research_fails(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        result = runner.invoke(
            app,
            [
                "research",
                "verify",
                "--research-id",
                str(uuid4()),
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code == 1
        assert "ResearchNotes artifact not found" in result.output

    def test_invalid_uuid_rejected(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        result = runner.invoke(
            app,
            [
                "research",
                "verify",
                "--research-id",
                "not-a-uuid",
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code != 0


class TestBriefGenerate:
    def test_generates_and_persists(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)
        research_id = _create_verified_research(content_root, topic_id)

        brief_json = json.dumps(
            {
                "problem": "Full table scans are slow",
                "core_explanation": "Indexes let the database jump straight to matching rows",
                "example": "SELECT with and without an index",
                "takeaway": "Index your filter/sort columns",
                "cta": "Follow for more tips",
                "estimated_duration": 45,
                "visual_style": "clean animated diagrams",
            }
        )
        calls = _patch_gemini_provider(monkeypatch, brief_json)

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
        assert len(calls) == 1
        assert calls[0]["operation"] == "brief"

        brief_id = _extract(result.output, "brief_id")
        store = ContentStore(content_root)
        brief = store.load_content_brief(UUID(brief_id))
        assert brief.topic == "Why Database Indexes Make Queries Faster"
        assert brief.sources == ["https://www.postgresql.org/docs/current/indexes.html"]

    def test_blocked_when_research_not_ready(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)
        create_result = runner.invoke(
            app, ["research", "create", "--topic-id", topic_id, "--content-root", str(content_root)]
        )
        research_id = _extract(create_result.output, "research_id")

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
        assert result.exit_code == 1
        assert "not ready for brief generation" in result.output

    def test_missing_research_fails(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)

        result = runner.invoke(
            app,
            [
                "brief",
                "generate",
                "--topic-id",
                topic_id,
                "--research-id",
                str(uuid4()),
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code == 1
        assert "ResearchNotes artifact not found" in result.output


class TestGeminiBudgetGate:
    def test_brief_generate_blocked_without_local_budget(self, tmp_path, monkeypatch):
        """The CLI must never bypass BudgetTracker, even indirectly."""
        content_root, _ = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)
        research_id = _create_verified_research(content_root, topic_id)

        budget_config = tmp_path / "budgets.yaml"
        budget_config.write_text(
            "budgets:\n"
            "  gemini:\n"
            "    model: null\n"
            "    period: provider-defined\n"
            "    official_limit:\n"
            "      requests_per_day: null\n"
            "      tokens_per_day: null\n"
            "    local_budget:\n"
            "      requests_per_day: null\n"
            "      tokens_per_day: null\n"
            "    warning_percent: 80\n"
            "    hard_stop_percent: 100\n"
            "    reserve_percent: 20\n"
            "    paid_fallback: false\n"
        )
        monkeypatch.setenv("BUDGET_CONFIG", str(budget_config))
        monkeypatch.setenv("GEMINI_MODEL", "gemini-test-model")
        monkeypatch.setenv("GEMINI_API_KEY", "sk-should-never-appear-in-output")

        with patch("content_engine.providers.gemini.provider.genai.Client"):
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

        assert result.exit_code == 1
        assert "No local budget configured" in result.output
        assert "sk-should-never-appear-in-output" not in result.output


class TestScriptGenerate:
    def test_generates_and_persists(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)
        research_id = _create_verified_research(content_root, topic_id)

        brief_json = json.dumps(
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
        _patch_gemini_provider(monkeypatch, brief_json)
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

        script_json = json.dumps(
            {
                "scenes": [
                    {"number": 1, "duration": 3.0, "narration": "Hook", "visual_prompt": "spinner"},
                    {
                        "number": 2,
                        "duration": 10.0,
                        "narration": "Explain",
                        "visual_prompt": "diagram",
                    },
                ]
            }
        )
        _patch_gemini_provider(monkeypatch, script_json)

        result = runner.invoke(
            app, ["script", "generate", "--brief-id", brief_id, "--content-root", str(content_root)]
        )
        assert result.exit_code == 0, result.output

        script_id = _extract(result.output, "script_id")
        store = ContentStore(content_root)
        script = store.load_script(UUID(script_id))
        assert [s.number for s in script.scenes] == [1, 2]
        assert script.brief_id == UUID(brief_id)

    def test_missing_brief_fails(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        _patch_gemini_provider(monkeypatch, "{}")

        result = runner.invoke(
            app,
            ["script", "generate", "--brief-id", str(uuid4()), "--content-root", str(content_root)],
        )
        assert result.exit_code == 1
        assert "ContentBrief artifact not found" in result.output


class TestStoryboardGenerate:
    def test_generates_and_persists_preserving_narration(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        topic_id = _create_topic(content_root)
        research_id = _create_verified_research(content_root, topic_id)

        brief_json = json.dumps(
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
        _patch_gemini_provider(monkeypatch, brief_json)
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

        script_json = json.dumps(
            {
                "scenes": [
                    {"number": 1, "duration": 3.0, "narration": "Hook", "visual_prompt": "spinner"},
                    {
                        "number": 2,
                        "duration": 10.0,
                        "narration": "Explain",
                        "visual_prompt": "diagram",
                    },
                ]
            }
        )
        _patch_gemini_provider(monkeypatch, script_json)
        script_result = runner.invoke(
            app, ["script", "generate", "--brief-id", brief_id, "--content-root", str(content_root)]
        )
        script_id = _extract(script_result.output, "script_id")

        storyboard_json = json.dumps(
            {
                "scenes": [
                    {"number": 1, "visual_prompt": "enriched spinner"},
                    {"number": 2, "visual_prompt": "enriched diagram"},
                ]
            }
        )
        _patch_gemini_provider(monkeypatch, storyboard_json)

        result = runner.invoke(
            app,
            [
                "storyboard",
                "generate",
                "--script-id",
                script_id,
                "--brief-id",
                brief_id,
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code == 0, result.output

        storyboard_id = _extract(result.output, "storyboard_id")
        store = ContentStore(content_root)
        storyboard = store.load_storyboard(UUID(storyboard_id))

        # visual_prompt comes from the (faked) provider; every other field is
        # carried over verbatim from the Script by StoryboardService itself —
        # proof the CLI didn't reimplement that merge logic.
        assert storyboard.scenes[0].visual_prompt == "enriched spinner"
        assert storyboard.scenes[0].narration == "Hook"
        assert storyboard.scenes[0].duration == 3.0

    def test_missing_script_fails(self, tmp_path, monkeypatch):
        content_root, _ = _env(monkeypatch, tmp_path)
        _patch_gemini_provider(monkeypatch, "{}")

        result = runner.invoke(
            app,
            [
                "storyboard",
                "generate",
                "--script-id",
                str(uuid4()),
                "--brief-id",
                str(uuid4()),
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code == 1
        assert "Script artifact not found" in result.output
