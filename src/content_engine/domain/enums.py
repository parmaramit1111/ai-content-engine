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
