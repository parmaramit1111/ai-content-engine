"""Core domain models for topics, briefs, scripts, and scenes.

Models follow the domain entities described in ARCHITECTURE.md §13:
    Topic, ContentBrief, Script, Scene.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from content_engine.domain.enums import Category, Difficulty, TopicStatus


def utc_now() -> datetime:
    """Return the current UTC-aware datetime."""
    return datetime.now(UTC)


class Scene(BaseModel):
    """A single scene within a script (ARCHITECTURE §13 — Scene)."""

    number: int = Field(ge=1, description="Scene number, 1-indexed")
    duration: float = Field(ge=0, description="Scene duration in seconds")
    narration: str = Field(min_length=1, description="Voice-over text for the scene")
    visual_prompt: str = Field(min_length=1, description="Prompt describing the visual")
    onscreen_text: str | None = Field(default=None, description="Text displayed on screen")
    transition: str | None = Field(default=None, description="Transition to the next scene")


class Script(BaseModel):
    """A versioned script composed of ordered scenes (FR-04, ARCHITECTURE §13)."""

    id: UUID = Field(default_factory=uuid4)
    brief_id: UUID = Field(description="Reference to the ContentBrief this script is based on")
    version: int = Field(ge=1, default=1, description="Script version number, starting at 1")
    scenes: list[Scene] = Field(default_factory=list, description="Ordered list of scenes")


class ContentBrief(BaseModel):
    """Structured content brief (FR-03, PRD §4, ARCHITECTURE §13)."""

    id: UUID = Field(default_factory=uuid4)
    topic: str = Field(description="Topic title")
    problem: str = Field(description="Problem being addressed")
    core_explanation: str = Field(description="Core technical explanation")
    example: str = Field(description="Concrete example")
    takeaway: str = Field(description="Key takeaway")
    cta: str = Field(description="Call to action")
    sources: list[str] = Field(default_factory=list, description="Source references")
    estimated_duration: int = Field(ge=1, description="Estimated video duration in seconds")
    visual_style: str = Field(description="Visual style description")


class Topic(BaseModel):
    """A content topic in the production pipeline (FR-01, ARCHITECTURE §13)."""

    id: UUID = Field(default_factory=uuid4)
    title: str = Field(min_length=1, description="Topic title")
    category: Category = Field(description="Content category")
    audience: str = Field(description="Target audience")
    difficulty: Difficulty = Field(description="Target difficulty")
    hook: str = Field(min_length=1, description="Opening hook for the video")
    status: TopicStatus = Field(default=TopicStatus.IDEA, description="Current production status")
    source_refs: list[str] = Field(
        default_factory=list, description="Reference to source materials"
    )
    created_at: datetime = Field(default_factory=utc_now, description="When the topic was created")
    updated_at: datetime = Field(
        default_factory=utc_now, description="When the topic was last updated"
    )
