"""CLI tests for review create/approve/reject and package create.

A Production is constructed directly and persisted via ContentStore
(bypassing assemble/ffmpeg entirely) since review/package only need a
valid, already-assembled Production to reference by id.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

from typer.testing import CliRunner

from content_engine.cli import app
from content_engine.domain.models import Production
from content_engine.storage import ContentStore

runner = CliRunner()

_ALL_CATEGORIES = [
    "technical_accuracy",
    "sources",
    "clarity",
    "hook",
    "pacing",
    "visual_relevance",
    "ai_artifacts",
    "captions",
    "brand_consistency",
    "licensing",
]


def _env(monkeypatch, tmp_path: Path) -> Path:
    content_root = tmp_path / "content"
    monkeypatch.setenv("CONTENT_ROOT", str(content_root))
    return content_root


def _extract(output: str, key: str) -> str:
    for line in output.splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    raise AssertionError(f"{key}= not found in output:\n{output}")


def _create_production(content_root: Path) -> str:
    production = Production(
        script_id=uuid4(),
        storyboard_id=uuid4(),
        captions_path=str(content_root / "final.srt"),
        output_path=str(content_root / "final.mp4"),
    )
    ContentStore(content_root).save_production(production)
    return str(production.id)


def _checklist_path(tmp_path: Path, *, all_pass: bool, notes: str | None = None) -> Path:
    path = tmp_path / "checklist.json"
    payload = {category: {"passed": True} for category in _ALL_CATEGORIES}
    if not all_pass:
        payload["technical_accuracy"] = {"passed": False, "notes": notes or "needs a fix"}
    path.write_text(json.dumps(payload))
    return path


class TestReviewCreate:
    def test_create_starts_pending(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        production_id = _create_production(content_root)
        checklist = _checklist_path(tmp_path, all_pass=True)

        result = runner.invoke(
            app,
            [
                "review",
                "create",
                "--production-id",
                production_id,
                "--reviewer",
                "Amit Parmar",
                "--checklist",
                str(checklist),
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code == 0, result.output
        assert _extract(result.output, "status") == "pending"

    def test_missing_production_fails(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        checklist = _checklist_path(tmp_path, all_pass=True)

        result = runner.invoke(
            app,
            [
                "review",
                "create",
                "--production-id",
                str(uuid4()),
                "--reviewer",
                "Amit",
                "--checklist",
                str(checklist),
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code == 1
        assert "Production artifact not found" in result.output

    def test_incomplete_checklist_rejected_by_service(self, tmp_path, monkeypatch):
        """Category-coverage enforcement stays in ReviewService, not the CLI."""
        content_root = _env(monkeypatch, tmp_path)
        production_id = _create_production(content_root)
        checklist = tmp_path / "checklist.json"
        checklist.write_text(json.dumps({"technical_accuracy": {"passed": True}}))

        result = runner.invoke(
            app,
            [
                "review",
                "create",
                "--production-id",
                production_id,
                "--reviewer",
                "Amit",
                "--checklist",
                str(checklist),
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code == 1
        assert "Checklist missing required category" in result.output

    def test_unknown_category_rejected(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        production_id = _create_production(content_root)
        checklist = tmp_path / "checklist.json"
        payload = {category: {"passed": True} for category in _ALL_CATEGORIES}
        payload["not_a_real_category"] = {"passed": True}
        checklist.write_text(json.dumps(payload))

        result = runner.invoke(
            app,
            [
                "review",
                "create",
                "--production-id",
                production_id,
                "--reviewer",
                "Amit",
                "--checklist",
                str(checklist),
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code == 1
        assert "Unknown review category" in result.output


class TestReviewApproveReject:
    def test_approve_all_passing(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        production_id = _create_production(content_root)
        checklist = _checklist_path(tmp_path, all_pass=True)

        create_result = runner.invoke(
            app,
            [
                "review",
                "create",
                "--production-id",
                production_id,
                "--reviewer",
                "Amit",
                "--checklist",
                str(checklist),
                "--content-root",
                str(content_root),
            ],
        )
        review_id = _extract(create_result.output, "review_id")

        approve_result = runner.invoke(
            app,
            ["review", "approve", "--review-id", review_id, "--content-root", str(content_root)],
        )
        assert approve_result.exit_code == 0, approve_result.output
        assert _extract(approve_result.output, "status") == "approved"

    def test_approve_fails_with_failing_category(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        production_id = _create_production(content_root)
        checklist = _checklist_path(tmp_path, all_pass=False)

        create_result = runner.invoke(
            app,
            [
                "review",
                "create",
                "--production-id",
                production_id,
                "--reviewer",
                "Amit",
                "--checklist",
                str(checklist),
                "--content-root",
                str(content_root),
            ],
        )
        review_id = _extract(create_result.output, "review_id")

        approve_result = runner.invoke(
            app,
            ["review", "approve", "--review-id", review_id, "--content-root", str(content_root)],
        )
        assert approve_result.exit_code == 1
        assert "Cannot approve" in approve_result.output

    def test_reject_requires_actionable_notes(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        production_id = _create_production(content_root)
        checklist = _checklist_path(tmp_path, all_pass=False)

        create_result = runner.invoke(
            app,
            [
                "review",
                "create",
                "--production-id",
                production_id,
                "--reviewer",
                "Amit",
                "--checklist",
                str(checklist),
                "--content-root",
                str(content_root),
            ],
        )
        review_id = _extract(create_result.output, "review_id")

        reject_result = runner.invoke(
            app, ["review", "reject", "--review-id", review_id, "--content-root", str(content_root)]
        )
        assert reject_result.exit_code == 0, reject_result.output
        assert _extract(reject_result.output, "status") == "rejected"

    def test_approve_twice_fails_terminal_state(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        production_id = _create_production(content_root)
        checklist = _checklist_path(tmp_path, all_pass=True)

        create_result = runner.invoke(
            app,
            [
                "review",
                "create",
                "--production-id",
                production_id,
                "--reviewer",
                "Amit",
                "--checklist",
                str(checklist),
                "--content-root",
                str(content_root),
            ],
        )
        review_id = _extract(create_result.output, "review_id")

        runner.invoke(
            app,
            ["review", "approve", "--review-id", review_id, "--content-root", str(content_root)],
        )
        second = runner.invoke(
            app,
            ["review", "approve", "--review-id", review_id, "--content-root", str(content_root)],
        )
        assert second.exit_code == 1
        assert "already approved" in second.output

    def test_missing_review_fails(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        result = runner.invoke(
            app,
            ["review", "approve", "--review-id", str(uuid4()), "--content-root", str(content_root)],
        )
        assert result.exit_code == 1
        assert "Review artifact not found" in result.output


class TestPackageCreate:
    def test_package_requires_approved_review(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        production_id = _create_production(content_root)
        checklist = _checklist_path(tmp_path, all_pass=True)

        create_result = runner.invoke(
            app,
            [
                "review",
                "create",
                "--production-id",
                production_id,
                "--reviewer",
                "Amit",
                "--checklist",
                str(checklist),
                "--content-root",
                str(content_root),
            ],
        )
        review_id = _extract(create_result.output, "review_id")

        # PENDING, not yet approved.
        package_result = runner.invoke(
            app,
            [
                "package",
                "create",
                "--review-id",
                review_id,
                "--production-id",
                production_id,
                "--title",
                "Why Database Indexes Make Queries Faster",
                "--content-root",
                str(content_root),
            ],
        )
        assert package_result.exit_code == 1
        assert "not approved" in package_result.output

    def test_package_created_from_approved_review(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        production_id = _create_production(content_root)
        checklist = _checklist_path(tmp_path, all_pass=True)

        create_result = runner.invoke(
            app,
            [
                "review",
                "create",
                "--production-id",
                production_id,
                "--reviewer",
                "Amit",
                "--checklist",
                str(checklist),
                "--content-root",
                str(content_root),
            ],
        )
        review_id = _extract(create_result.output, "review_id")
        runner.invoke(
            app,
            ["review", "approve", "--review-id", review_id, "--content-root", str(content_root)],
        )

        package_result = runner.invoke(
            app,
            [
                "package",
                "create",
                "--review-id",
                review_id,
                "--production-id",
                production_id,
                "--title",
                "Why Database Indexes Make Queries Faster",
                "--source",
                "https://www.postgresql.org/docs/current/indexes.html",
                "--content-root",
                str(content_root),
            ],
        )
        assert package_result.exit_code == 0, package_result.output

        package_id = _extract(package_result.output, "package_id")
        store = ContentStore(content_root)
        package = store.load_publication_package(UUID(package_id))
        assert package.title == "Why Database Indexes Make Queries Faster"
        assert package.review_id == UUID(review_id)

    def test_missing_review_fails(self, tmp_path, monkeypatch):
        content_root = _env(monkeypatch, tmp_path)
        production_id = _create_production(content_root)

        result = runner.invoke(
            app,
            [
                "package",
                "create",
                "--review-id",
                str(uuid4()),
                "--production-id",
                production_id,
                "--title",
                "x",
                "--content-root",
                str(content_root),
            ],
        )
        assert result.exit_code == 1
        assert "Review artifact not found" in result.output
