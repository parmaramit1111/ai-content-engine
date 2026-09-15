"""Domain enums for content categories, difficulties, and production statuses."""

from enum import StrEnum


class TopicStatus(StrEnum):
    """Production workflow statuses for a Topic (PRD §5, FR-01)."""

    IDEA = "IDEA"
    RESEARCHING = "RESEARCHING"
    SCRIPTED = "SCRIPTED"
    STORYBOARDED = "STORYBOARDED"
    GENERATING = "GENERATING"
    EDITING = "EDITING"
    REVIEW = "REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    ANALYZING = "ANALYZING"
    ARCHIVED = "ARCHIVED"


class Category(StrEnum):
    """Content categories (PRD §4 — Initial Content Positioning)."""

    AI_ENGINEERING = "ai_engineering"
    BACKEND_ENGINEERING = "backend_engineering"
    ARCHITECTURE = "architecture"
    ENGINEERING_LESSONS = "engineering_lessons"


class Difficulty(StrEnum):
    """Target difficulty level for a topic (FR-01)."""

    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class ResearchVerificationStatus(StrEnum):
    """Human verification status for research notes (PRD §6, FR-02; ARCHITECTURE §8)."""

    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    REJECTED = "rejected"


class AssetType(StrEnum):
    """Media type of an imported visual Asset (PRD FR-06; ARCHITECTURE §13).

    Only VIDEO is defined for Phase 09 — Google Flow's only output this
    project imports today. Not adding IMAGE/AUDIO speculatively.

    Phase 10 audio is represented by the separate ``AudioTrack`` model,
    not by extending this enum — narration/audio is production-level,
    not scene-level visual media.
    """

    VIDEO = "video"


class ProductionStatus(StrEnum):
    """Result status of an assembled Production (PRD FR-08; ARCHITECTURE §13).

    Only ASSEMBLED is defined for Phase 10 — a Production is only ever
    constructed after a successful assembly; failures raise
    VideoAssemblyServiceError rather than producing a failed record.
    Review/publish states belong to a later phase if ever needed.
    """

    ASSEMBLED = "assembled"
