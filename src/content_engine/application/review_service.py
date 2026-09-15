"""Human review and publication-packaging service.

Implements the Phase 11 vertical slice:

    Production
        → ReviewService.create_review()
        → Review (PENDING)
        → ReviewService.approve() / ReviewService.reject()
        → Review (APPROVED / REJECTED — terminal)
        → ReviewService.create_publication_package()   # only from APPROVED
        → PublicationPackage

No provider, no budget-tracker, no FFmpeg, no CLI, no persistence, and no
publishing action of any kind — Gemini/NotebookLM/Google Flow/YouTube/HTTP
are never referenced here. Approval and rejection are always explicit,
separate operations: creating a Review never implies a decision, and
neither APPROVED nor REJECTED can ever be changed once reached.
"""

from __future__ import annotations

from typing import Any

from content_engine.domain.enums import ReviewCategory, ReviewStatus
from content_engine.domain.models import (
    ChecklistItem,
    Production,
    PublicationPackage,
    Review,
    utc_now,
)

_REQUIRED_CATEGORIES: frozenset[ReviewCategory] = frozenset(ReviewCategory)


class ReviewServiceError(Exception):
    """Raised when review creation, decision, or packaging validation fails."""


class ReviewService:
    """Create reviews, record explicit approve/reject decisions, and package approved productions.

    No persistence — every method takes and returns plain domain objects
    and never mutates its inputs; ``approve``/``reject`` return a new
    ``Review`` via ``model_copy``, matching the existing service
    convention (e.g. ``StoryboardService`` rebuilding ``Scene`` objects).
    """

    def create_review(
        self,
        production: Production,
        reviewer: str,
        checklist: dict[ReviewCategory, ChecklistItem],
    ) -> Review:
        """Create a new PENDING Review for a Production.

        Creating a review never implies approval — status is always
        PENDING and reviewed_at is always None, regardless of the
        checklist's content.

        Raises:
            ReviewServiceError: If reviewer is empty, or the checklist does
                not cover exactly the ten required categories.
        """
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise ReviewServiceError("reviewer is missing or empty")

        self._ensure_exact_category_coverage(checklist)

        return Review(
            production_id=production.id,
            reviewer=reviewer.strip(),
            checklist=dict(checklist),
        )

    def approve(self, review: Review) -> Review:
        """Explicitly approve a PENDING review.

        Raises:
            ReviewServiceError: If the review is not PENDING (a terminal
                decision cannot be changed), if the checklist is missing a
                required category, or if any category has not passed.
        """
        self._ensure_pending(review)
        self._ensure_exact_category_coverage(review.checklist)

        failing = sorted(
            category.value for category, item in review.checklist.items() if not item.passed
        )
        if failing:
            raise ReviewServiceError(f"Cannot approve: category(ies) have not passed: {failing}")

        return review.model_copy(
            update={"status": ReviewStatus.APPROVED, "reviewed_at": utc_now()}
        )

    def reject(self, review: Review) -> Review:
        """Explicitly reject a PENDING review.

        Raises:
            ReviewServiceError: If the review is not PENDING (a terminal
                decision cannot be changed), if no checklist category has
                failed, or if any failed category lacks an actionable note.
        """
        self._ensure_pending(review)
        self._ensure_exact_category_coverage(review.checklist)

        failing_items = {
            category: item for category, item in review.checklist.items() if not item.passed
        }
        if not failing_items:
            raise ReviewServiceError("Cannot reject: no checklist category has failed")

        unexplained = sorted(
            category.value
            for category, item in failing_items.items()
            if not item.notes or not item.notes.strip()
        )
        if unexplained:
            raise ReviewServiceError(
                f"Cannot reject: failed category(ies) missing actionable notes: {unexplained}"
            )

        return review.model_copy(
            update={"status": ReviewStatus.REJECTED, "reviewed_at": utc_now()}
        )

    def create_publication_package(
        self,
        review: Review,
        production: Production,
        title: str,
        sources: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PublicationPackage:
        """Create a PublicationPackage from an approved Review.

        This is the actual human-approval gate: packaging is impossible
        for PENDING or REJECTED reviews.

        Raises:
            ReviewServiceError: If the review does not belong to the given
                production, is not APPROVED, or title is empty.
        """
        if review.production_id != production.id:
            raise ReviewServiceError(
                f"Review {review.id} belongs to production {review.production_id}, "
                f"not the requested production {production.id}"
            )

        if review.status != ReviewStatus.APPROVED:
            raise ReviewServiceError(
                f"Cannot package: review {review.id} is {review.status.value}, not approved"
            )

        if not isinstance(title, str) or not title.strip():
            raise ReviewServiceError("title is missing or empty")

        return PublicationPackage(
            production_id=production.id,
            review_id=review.id,
            output_path=production.output_path,
            captions_path=production.captions_path,
            title=title.strip(),
            sources=list(sources) if sources else [],
            metadata=metadata,
        )

    @staticmethod
    def _ensure_pending(review: Review) -> None:
        if review.status != ReviewStatus.PENDING:
            raise ReviewServiceError(
                f"Review {review.id} is already {review.status.value}; "
                f"a terminal review decision cannot be changed"
            )

    @staticmethod
    def _ensure_exact_category_coverage(checklist: dict[ReviewCategory, ChecklistItem]) -> None:
        provided = set(checklist.keys())

        missing = sorted(c.value for c in _REQUIRED_CATEGORIES - provided)
        if missing:
            raise ReviewServiceError(f"Checklist missing required category(ies): {missing}")

        extra = sorted(str(c) for c in provided - _REQUIRED_CATEGORIES)
        if extra:
            raise ReviewServiceError(f"Checklist contains unexpected category(ies): {extra}")
