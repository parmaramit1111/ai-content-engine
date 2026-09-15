"""Unit tests for the Review/ChecklistItem/PublicationPackage domain models
and the ReviewCategory/ReviewStatus enums.

Covers:
- ChecklistItem: valid creation, notes optional
- Review: valid creation, defaults to PENDING, id/timestamp conventions
- ReviewCategory: exactly the ten required categories
- ReviewStatus: exactly the three required statuses
- PublicationPackage: valid creation, required fields, default sources,
  JSON round-trip
"""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from content_engine.domain.enums import ReviewCategory, ReviewStatus
from content_engine.domain.models import ChecklistItem, PublicationPackage, Review


def _full_checklist(all_pass: bool = True) -> dict[ReviewCategory, ChecklistItem]:
    return {category: ChecklistItem(passed=all_pass) for category in ReviewCategory}


def _make_review(**overrides) -> Review:
    defaults = {
        "production_id": uuid4(),
        "reviewer": "Amit Parmar",
        "checklist": _full_checklist(),
    }
    defaults.update(overrides)
    return Review(**defaults)


def _make_package(**overrides) -> PublicationPackage:
    defaults = {
        "production_id": uuid4(),
        "review_id": uuid4(),
        "output_path": "/assets/final/prod-1.mp4",
        "captions_path": "/assets/subtitles/prod-1.srt",
        "title": "What is RAG?",
    }
    defaults.update(overrides)
    return PublicationPackage(**defaults)


class TestReviewCategoryEnum:
    def test_has_exactly_ten_required_categories(self):
        assert {c.value for c in ReviewCategory} == {
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
        }


class TestReviewStatusEnum:
    def test_has_exactly_three_statuses(self):
        assert {s.value for s in ReviewStatus} == {"pending", "approved", "rejected"}


class TestChecklistItem:
    def test_valid_creation(self):
        item = ChecklistItem(passed=True)
        assert item.passed is True
        assert item.notes is None

    def test_notes_optional_but_accepted(self):
        item = ChecklistItem(passed=False, notes="Hook doesn't match the audio track")
        assert item.notes == "Hook doesn't match the audio track"

    def test_passed_is_required(self):
        with pytest.raises(ValidationError, match="Field required"):
            ChecklistItem()


class TestReviewCreation:
    def test_valid_creation(self):
        review = _make_review()
        assert isinstance(review, Review)
        assert isinstance(review.id, UUID)
        assert len(review.checklist) == 10

    def test_id_auto_generated_and_unique(self):
        r1 = _make_review()
        r2 = _make_review()
        assert r1.id != r2.id

    def test_defaults_to_pending(self):
        review = _make_review()
        assert review.status == ReviewStatus.PENDING

    def test_reviewed_at_defaults_to_none(self):
        review = _make_review()
        assert review.reviewed_at is None

    def test_created_at_is_set(self):
        review = _make_review()
        assert review.created_at is not None

    def test_production_id_association(self):
        production_id = uuid4()
        review = _make_review(production_id=production_id)
        assert review.production_id == production_id

    def test_checklist_holds_all_categories(self):
        review = _make_review()
        assert set(review.checklist.keys()) == set(ReviewCategory)


class TestReviewValidation:
    def test_missing_production_id_raises(self):
        with pytest.raises(ValidationError, match="Field required"):
            Review(reviewer="Amit", checklist=_full_checklist())

    def test_empty_reviewer_raises(self):
        with pytest.raises(ValidationError):
            Review(production_id=uuid4(), reviewer="", checklist=_full_checklist())

    def test_missing_checklist_raises(self):
        with pytest.raises(ValidationError, match="Field required"):
            Review(production_id=uuid4(), reviewer="Amit")

    def test_invalid_category_key_rejected(self):
        with pytest.raises(ValidationError):
            Review(
                production_id=uuid4(),
                reviewer="Amit",
                checklist={"not_a_real_category": ChecklistItem(passed=True)},
            )


class TestReviewJSON:
    def test_json_round_trip(self):
        review = _make_review()
        data = review.model_dump_json()
        restored = Review.model_validate_json(data)
        assert restored.id == review.id
        assert restored.production_id == review.production_id
        assert restored.status == ReviewStatus.PENDING
        assert len(restored.checklist) == 10


class TestPublicationPackageCreation:
    def test_valid_creation(self):
        package = _make_package()
        assert isinstance(package, PublicationPackage)
        assert isinstance(package.id, UUID)
        assert package.title == "What is RAG?"

    def test_id_auto_generated_and_unique(self):
        p1 = _make_package()
        p2 = _make_package()
        assert p1.id != p2.id

    def test_sources_defaults_to_empty_list(self):
        package = _make_package()
        assert package.sources == []

    def test_metadata_defaults_to_none(self):
        package = _make_package()
        assert package.metadata is None

    def test_sources_and_metadata_accepted(self):
        package = _make_package(
            sources=["https://arxiv.org/abs/1706.01618"], metadata={"description": "A short intro"}
        )
        assert package.sources == ["https://arxiv.org/abs/1706.01618"]
        assert package.metadata == {"description": "A short intro"}

    def test_created_at_is_set(self):
        package = _make_package()
        assert package.created_at is not None


class TestPublicationPackageValidation:
    def test_missing_production_id_raises(self):
        with pytest.raises(ValidationError, match="Field required"):
            PublicationPackage(
                review_id=uuid4(),
                output_path="/x.mp4",
                captions_path="/x.srt",
                title="x",
            )

    def test_missing_review_id_raises(self):
        with pytest.raises(ValidationError, match="Field required"):
            PublicationPackage(
                production_id=uuid4(),
                output_path="/x.mp4",
                captions_path="/x.srt",
                title="x",
            )

    def test_missing_output_path_raises(self):
        with pytest.raises(ValidationError, match="Field required"):
            PublicationPackage(
                production_id=uuid4(), review_id=uuid4(), captions_path="/x.srt", title="x"
            )

    def test_missing_title_raises(self):
        with pytest.raises(ValidationError):
            PublicationPackage(
                production_id=uuid4(),
                review_id=uuid4(),
                output_path="/x.mp4",
                captions_path="/x.srt",
                title="",
            )


class TestPublicationPackageJSON:
    def test_json_round_trip(self):
        package = _make_package(sources=["https://example.com"])
        data = package.model_dump_json()
        restored = PublicationPackage.model_validate_json(data)
        assert restored.id == package.id
        assert restored.production_id == package.production_id
        assert restored.review_id == package.review_id
        assert restored.sources == ["https://example.com"]
