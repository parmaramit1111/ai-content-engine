"""Focused unit tests for ReviewService.

Covers: create_review validation, approve/reject decision logic and
terminal-state enforcement, create_publication_package gating, and
provider/budget/media isolation. Fully deterministic — no providers, no
filesystem, no subprocess involved anywhere in this phase.
"""

import ast
from inspect import getsource
from uuid import uuid4

import pytest

from content_engine.application import review_service as review_service_module
from content_engine.application.review_service import ReviewService, ReviewServiceError
from content_engine.domain.enums import ReviewCategory, ReviewStatus
from content_engine.domain.models import ChecklistItem, Production


def _full_checklist(all_pass: bool = True, notes: str | None = None) -> dict:
    return {
        category: ChecklistItem(passed=all_pass, notes=notes) for category in ReviewCategory
    }


def _make_production(**overrides) -> Production:
    defaults = {
        "script_id": uuid4(),
        "storyboard_id": uuid4(),
        "asset_ids": [uuid4()],
        "captions_path": "/assets/subtitles/prod-1.srt",
        "output_path": "/assets/final/prod-1.mp4",
    }
    defaults.update(overrides)
    return Production(**defaults)


class TestCreateReview:
    def test_complete_checklist_succeeds(self):
        service = ReviewService()
        production = _make_production()

        review = service.create_review(production, "Amit Parmar", _full_checklist())

        assert review.production_id == production.id
        assert review.reviewer == "Amit Parmar"

    def test_result_is_pending(self):
        service = ReviewService()
        review = service.create_review(_make_production(), "Amit", _full_checklist())
        assert review.status == ReviewStatus.PENDING

    def test_reviewed_at_is_none(self):
        service = ReviewService()
        review = service.create_review(_make_production(), "Amit", _full_checklist())
        assert review.reviewed_at is None

    def test_missing_category_rejected(self):
        service = ReviewService()
        checklist = _full_checklist()
        del checklist[ReviewCategory.HOOK]

        with pytest.raises(ReviewServiceError, match=r"missing required category.*hook"):
            service.create_review(_make_production(), "Amit", checklist)

    def test_empty_reviewer_rejected(self):
        service = ReviewService()

        with pytest.raises(ReviewServiceError, match="reviewer is missing or empty"):
            service.create_review(_make_production(), "   ", _full_checklist())

    def test_creating_review_never_mutates_supplied_checklist(self):
        service = ReviewService()
        checklist = _full_checklist()
        original = dict(checklist)

        service.create_review(_make_production(), "Amit", checklist)

        assert checklist == original


class TestApprove:
    def test_all_passing_becomes_approved(self):
        service = ReviewService()
        review = service.create_review(_make_production(), "Amit", _full_checklist(all_pass=True))

        approved = service.approve(review)

        assert approved.status == ReviewStatus.APPROVED

    def test_reviewed_at_populated(self):
        service = ReviewService()
        review = service.create_review(_make_production(), "Amit", _full_checklist(all_pass=True))

        approved = service.approve(review)

        assert approved.reviewed_at is not None

    def test_original_review_unchanged(self):
        service = ReviewService()
        review = service.create_review(_make_production(), "Amit", _full_checklist(all_pass=True))

        service.approve(review)

        assert review.status == ReviewStatus.PENDING
        assert review.reviewed_at is None

    def test_failed_category_blocks_approval(self):
        service = ReviewService()
        checklist = _full_checklist(all_pass=True)
        checklist[ReviewCategory.CAPTIONS] = ChecklistItem(passed=False, notes="Typo in captions")
        review = service.create_review(_make_production(), "Amit", checklist)

        with pytest.raises(ReviewServiceError, match=r"have not passed.*captions"):
            service.approve(review)

    def test_approved_cannot_be_approved_again(self):
        service = ReviewService()
        review = service.create_review(_make_production(), "Amit", _full_checklist(all_pass=True))
        approved = service.approve(review)

        with pytest.raises(ReviewServiceError, match="already approved"):
            service.approve(approved)

    def test_approved_cannot_be_rejected(self):
        service = ReviewService()
        review = service.create_review(_make_production(), "Amit", _full_checklist(all_pass=True))
        approved = service.approve(review)

        with pytest.raises(ReviewServiceError, match="already approved"):
            service.reject(approved)


class TestReject:
    def test_one_failed_category_with_notes_becomes_rejected(self):
        service = ReviewService()
        checklist = _full_checklist(all_pass=True)
        checklist[ReviewCategory.HOOK] = ChecklistItem(
            passed=False, notes="Hook does not match narration"
        )
        review = service.create_review(_make_production(), "Amit", checklist)

        rejected = service.reject(review)

        assert rejected.status == ReviewStatus.REJECTED

    def test_reviewed_at_populated(self):
        service = ReviewService()
        checklist = _full_checklist(all_pass=True)
        checklist[ReviewCategory.HOOK] = ChecklistItem(passed=False, notes="Needs work")
        review = service.create_review(_make_production(), "Amit", checklist)

        rejected = service.reject(review)

        assert rejected.reviewed_at is not None

    def test_original_review_unchanged(self):
        service = ReviewService()
        checklist = _full_checklist(all_pass=True)
        checklist[ReviewCategory.HOOK] = ChecklistItem(passed=False, notes="Needs work")
        review = service.create_review(_make_production(), "Amit", checklist)

        service.reject(review)

        assert review.status == ReviewStatus.PENDING
        assert review.reviewed_at is None

    def test_no_failed_categories_rejected(self):
        service = ReviewService()
        review = service.create_review(_make_production(), "Amit", _full_checklist(all_pass=True))

        with pytest.raises(ReviewServiceError, match="no checklist category has failed"):
            service.reject(review)

    def test_failed_category_without_notes_rejected(self):
        service = ReviewService()
        checklist = _full_checklist(all_pass=True)
        checklist[ReviewCategory.HOOK] = ChecklistItem(passed=False, notes=None)
        review = service.create_review(_make_production(), "Amit", checklist)

        with pytest.raises(ReviewServiceError, match=r"missing actionable notes.*hook"):
            service.reject(review)

    def test_failed_category_with_whitespace_only_notes_rejected(self):
        service = ReviewService()
        checklist = _full_checklist(all_pass=True)
        checklist[ReviewCategory.HOOK] = ChecklistItem(passed=False, notes="   ")
        review = service.create_review(_make_production(), "Amit", checklist)

        with pytest.raises(ReviewServiceError, match="missing actionable notes"):
            service.reject(review)

    def test_rejected_cannot_be_rejected_again(self):
        service = ReviewService()
        checklist = _full_checklist(all_pass=True)
        checklist[ReviewCategory.HOOK] = ChecklistItem(passed=False, notes="Needs work")
        review = service.create_review(_make_production(), "Amit", checklist)
        rejected = service.reject(review)

        with pytest.raises(ReviewServiceError, match="already rejected"):
            service.reject(rejected)

    def test_rejected_cannot_be_approved(self):
        service = ReviewService()
        checklist = _full_checklist(all_pass=True)
        checklist[ReviewCategory.HOOK] = ChecklistItem(passed=False, notes="Needs work")
        review = service.create_review(_make_production(), "Amit", checklist)
        rejected = service.reject(review)

        with pytest.raises(ReviewServiceError, match="already rejected"):
            service.approve(rejected)


class TestCreatePublicationPackage:
    def test_approved_review_and_matching_production_succeeds(self):
        service = ReviewService()
        production = _make_production()
        review = service.create_review(production, "Amit", _full_checklist(all_pass=True))
        approved = service.approve(review)

        package = service.create_publication_package(approved, production, title="What is RAG?")

        assert package.production_id == production.id
        assert package.review_id == approved.id

    def test_output_path_copied_correctly(self):
        service = ReviewService()
        production = _make_production(output_path="/assets/final/specific.mp4")
        review = service.create_review(production, "Amit", _full_checklist(all_pass=True))
        approved = service.approve(review)

        package = service.create_publication_package(approved, production, title="Title")

        assert package.output_path == "/assets/final/specific.mp4"

    def test_captions_path_copied_correctly(self):
        service = ReviewService()
        production = _make_production(captions_path="/assets/subtitles/specific.srt")
        review = service.create_review(production, "Amit", _full_checklist(all_pass=True))
        approved = service.approve(review)

        package = service.create_publication_package(approved, production, title="Title")

        assert package.captions_path == "/assets/subtitles/specific.srt"

    def test_pending_review_rejected(self):
        service = ReviewService()
        production = _make_production()
        review = service.create_review(production, "Amit", _full_checklist(all_pass=True))

        with pytest.raises(ReviewServiceError, match="is pending, not approved"):
            service.create_publication_package(review, production, title="Title")

    def test_rejected_review_rejected(self):
        service = ReviewService()
        production = _make_production()
        checklist = _full_checklist(all_pass=True)
        checklist[ReviewCategory.HOOK] = ChecklistItem(passed=False, notes="Needs work")
        review = service.create_review(production, "Amit", checklist)
        rejected = service.reject(review)

        with pytest.raises(ReviewServiceError, match="is rejected, not approved"):
            service.create_publication_package(rejected, production, title="Title")

    def test_mismatched_production_rejected(self):
        service = ReviewService()
        production = _make_production()
        other_production = _make_production()
        review = service.create_review(production, "Amit", _full_checklist(all_pass=True))
        approved = service.approve(review)

        with pytest.raises(ReviewServiceError, match="belongs to production"):
            service.create_publication_package(approved, other_production, title="Title")

    def test_empty_title_rejected(self):
        service = ReviewService()
        production = _make_production()
        review = service.create_review(production, "Amit", _full_checklist(all_pass=True))
        approved = service.approve(review)

        with pytest.raises(ReviewServiceError, match="title is missing or empty"):
            service.create_publication_package(approved, production, title="   ")

    def test_sources_and_metadata_passed_through(self):
        service = ReviewService()
        production = _make_production()
        review = service.create_review(production, "Amit", _full_checklist(all_pass=True))
        approved = service.approve(review)

        package = service.create_publication_package(
            approved,
            production,
            title="Title",
            sources=["https://example.com"],
            metadata={"description": "desc"},
        )

        assert package.sources == ["https://example.com"]
        assert package.metadata == {"description": "desc"}


class TestReviewServiceIsolation:
    def test_no_provider_budget_or_media_execution_import(self):
        """Phase 11 must remain independent of Gemini, NotebookLM, Flow,
        BudgetTracker, YouTube, HTTP clients, subprocess, and FFmpeg."""
        tree = ast.parse(getsource(review_service_module))
        imported_names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imported_names.append(module)
                imported_names.extend(f"{module}.{alias.name}" for alias in node.names)

        joined = " ".join(imported_names).lower()
        for forbidden in (
            "gemini",
            "google",
            "flow",
            "budget",
            "youtube",
            "requests",
            "httpx",
            "subprocess",
            "ffmpeg",
        ):
            assert forbidden not in joined, f"unexpected '{forbidden}' import in review_service"

    def test_no_publish_method_exists(self):
        """No automatic publishing action of any kind should exist on the service."""
        public_methods = [
            name
            for name in dir(ReviewService)
            if not name.startswith("_") and callable(getattr(ReviewService, name))
        ]
        for name in public_methods:
            assert "publish" not in name.lower()
            assert "upload" not in name.lower()
