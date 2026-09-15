"""Core domain models for topics, research notes, briefs, scripts, scenes, storyboards,
assets, audio tracks, productions, reviews, and publication packages.

Models follow the domain entities described in ARCHITECTURE.md §13:
    Topic, ResearchNotes, ContentBrief, Script, Scene, Asset, Production.

``Storyboard`` extends this set for Phase 08 (PRD FR-05, FR-06),
``AudioTrack`` extends it for Phase 10 (PRD FR-07), and ``Review``/
``PublicationPackage`` extend it for Phase 11 (PRD FR-10, FR-11); none of
these three are separately enumerated in ARCHITECTURE §13.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from content_engine.domain.enums import (
    AssetType,
    Category,
    Difficulty,
    ProductionStatus,
    ResearchVerificationStatus,
    ReviewCategory,
    ReviewStatus,
    TopicStatus,
)


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


class Storyboard(BaseModel):
    """Scene-level storyboard derived from a validated Script (PRD FR-05, FR-06).

    Reuses ``Scene`` as-is — no separate ``StoryboardScene`` type. A storyboard's
    scenes carry the same structural fields as the source ``Script``'s scenes
    (number, duration, narration, onscreen_text, transition); only
    ``visual_prompt`` is expected to differ, enriched for visual generation.
    """

    id: UUID = Field(default_factory=uuid4)
    script_id: UUID = Field(description="Reference to the Script this storyboard is based on")
    scenes: list[Scene] = Field(default_factory=list, description="Ordered list of scenes")


class Asset(BaseModel):
    """A human-imported visual asset associated with a Storyboard scene.

    PRD FR-06; ARCHITECTURE §13.

    Represents a Google Flow (or other human-produced) video clip that has
    been brought into the local workflow and validated. References its
    storyboard and scene by id/number only — it does not duplicate any
    Storyboard/Scene field.

    Multiple assets may exist for the same (storyboard_id, scene_number):
    asset selection is not this model's concern.
    """

    id: UUID = Field(default_factory=uuid4)
    storyboard_id: UUID = Field(description="Reference to the Storyboard this asset belongs to")
    scene_number: int = Field(ge=1, description="Scene number within the storyboard")
    type: AssetType = Field(default=AssetType.VIDEO, description="Media type of the asset")
    path: str = Field(description="Resolved local filesystem path to the asset file")
    source: str = Field(description="High-level provenance, e.g. 'google_flow', 'manual'")
    provider: str | None = Field(
        default=None, description="Specific generation provider/model, e.g. 'veo-3.1-fast'"
    )
    flow_credits_used: int | None = Field(
        default=None, ge=1, description="Human-reported Flow credits spent on this asset"
    )
    metadata: dict[str, Any] | None = Field(
        default=None, description="Additional human-supplied metadata"
    )
    created_at: datetime = Field(default_factory=utc_now, description="When the asset was imported")


class AudioTrack(BaseModel):
    """A human-imported production-level narration/audio track (PRD FR-07; ARCHITECTURE §13).

    Unlike ``Asset``, which is scene-level visual media, an AudioTrack is not
    tied to a single scene — it represents narration/audio for the whole
    production. References its storyboard by id only; does not duplicate
    any Storyboard/Scene field. No TTS/audio generation happens here — the
    file already exists and is only validated/described.
    """

    id: UUID = Field(default_factory=uuid4)
    storyboard_id: UUID = Field(
        description="Reference to the Storyboard this audio track belongs to"
    )
    path: str = Field(description="Resolved local filesystem path to the audio file")
    source: str = Field(description="High-level provenance, e.g. 'human_narration', 'local_tts'")
    provider: str | None = Field(
        default=None, description="Specific generation provider/tool, e.g. 'google_tts'"
    )
    metadata: dict[str, Any] | None = Field(
        default=None, description="Additional human-supplied metadata"
    )
    created_at: datetime = Field(
        default_factory=utc_now, description="When the audio track was imported"
    )


class Production(BaseModel):
    """A successfully assembled video production (PRD FR-08; ARCHITECTURE §13).

    Only ever constructed after a successful assembly by
    ``VideoAssemblyService.assemble()`` — assembly failures raise
    ``VideoAssemblyServiceError`` rather than producing a failed record.
    References other models by id only; never embeds full domain objects.
    """

    id: UUID = Field(default_factory=uuid4)
    script_id: UUID = Field(description="Reference to the Script this production is based on")
    storyboard_id: UUID = Field(
        description="Reference to the Storyboard this production was assembled from"
    )
    asset_ids: list[UUID] = Field(
        default_factory=list, description="Visual Assets used, one per scene"
    )
    audio_track_id: UUID | None = Field(
        default=None, description="AudioTrack used, if any"
    )
    captions_path: str = Field(description="Path to the generated SRT captions file")
    output_path: str = Field(description="Path to the final assembled MP4")
    status: ProductionStatus = Field(
        default=ProductionStatus.ASSEMBLED, description="Result status of the assembly"
    )
    created_at: datetime = Field(
        default_factory=utc_now, description="When the production was assembled"
    )


class ChecklistItem(BaseModel):
    """One reviewed category's pass/fail result and actionable note (PRD FR-10).

    A single combined structure rather than a separate checklist dict plus
    a parallel findings list, so a category's finding can never drift out
    of sync with its pass/fail result.
    """

    passed: bool = Field(description="Whether this category passed review")
    notes: str | None = Field(
        default=None, description="Actionable note, expected when passed is False"
    )


class Review(BaseModel):
    """A human review decision record for a Production (PRD FR-10; ARCHITECTURE §14, §19).

    References its Production by id only — never embeds or modifies it;
    ``Production`` remains immutable. Always starts ``PENDING``; creating a
    Review never implies approval. ``ReviewService`` enforces that
    ``APPROVED``/``REJECTED`` are terminal — this model only names the
    possible states and carries the decision once made.
    """

    id: UUID = Field(default_factory=uuid4)
    production_id: UUID = Field(description="Reference to the Production being reviewed")
    reviewer: str = Field(min_length=1, description="Human reviewer identifier/name")
    checklist: dict[ReviewCategory, ChecklistItem] = Field(
        description="Pass/fail + notes for each of the ten required review categories"
    )
    status: ReviewStatus = Field(
        default=ReviewStatus.PENDING, description="Current human decision state"
    )
    reviewed_at: datetime | None = Field(
        default=None, description="When the final approve/reject decision was made"
    )
    created_at: datetime = Field(default_factory=utc_now, description="When the review was created")


class PublicationPackage(BaseModel):
    """A preparation artifact for manual publication (PRD FR-11; ARCHITECTURE §14, §19).

    Only ever produced from an APPROVED Review — packaging is the actual
    human-approval gate. Copies only the two small path strings needed to
    identify the final artifact; everything else is referenced by id, not
    duplicated. No publishing action of any kind exists on this model.
    """

    id: UUID = Field(default_factory=uuid4)
    production_id: UUID = Field(description="Reference to the packaged Production")
    review_id: UUID = Field(description="Reference to the approving Review")
    output_path: str = Field(description="Copied from Production.output_path")
    captions_path: str = Field(description="Copied from Production.captions_path")
    title: str = Field(min_length=1, description="Publication title")
    sources: list[str] = Field(default_factory=list, description="Source references")
    metadata: dict[str, Any] | None = Field(
        default=None, description="Additional flexible publication metadata"
    )
    created_at: datetime = Field(
        default_factory=utc_now, description="When the package was created"
    )


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


class ResearchNotes(BaseModel):
    """Validated research notes supporting a content topic (PRD §6, FR-02; ARCHITECTURE §8, §13).

    Research is associated with a Topic via ``topic_id``. Source references are tracked
    in ``primary_sources``; ``Topic.source_refs`` is preserved separately and is not
    duplicated here.

    Required fields capture the minimum research information needed for brief generation:
    key facts, terminology, examples, caveats, primary sources, and visual concepts.

    Optional future metadata (notebooklm_session, source_notes, confidence_scores,
    annotations) supports human-in-the-loop NotebookLM workflows without claiming
    programmatic access to NotebookLM.
    """

    id: UUID = Field(default_factory=uuid4, description="Unique research record identifier")
    topic_id: UUID = Field(description="Reference to the Topic this research supports")
    key_facts: list[str] = Field(
        default_factory=list, description="Factual points gathered during research"
    )
    terminology: list[str] = Field(
        default_factory=list, description="Domain terms and definitions captured during research"
    )
    examples: list[str] = Field(
        default_factory=list, description="Concrete examples gathered during research"
    )
    caveats: list[str] = Field(
        default_factory=list, description="Known limitations or edge cases"
    )
    primary_sources: list[str] = Field(
        default_factory=list, description="Source references (URLs or identifiers)"
    )
    visual_concepts: list[str] = Field(
        default_factory=list, description="Visual directions tied to the topic"
    )
    verification_status: ResearchVerificationStatus = Field(
        default=ResearchVerificationStatus.UNVERIFIED,
        description="Human verification status of the research",
    )
    created_at: datetime = Field(
        default_factory=utc_now, description="When research was recorded"
    )
    updated_at: datetime = Field(
        default_factory=utc_now, description="When research was last updated"
    )

    # --- Optional future metadata (NOT required for Phase 06) ---
    notebooklm_session: str | None = Field(
        default=None,
        description="NotebookLM session ID/name (manual reference only — human-in-the-loop)",
    )
    source_notes: str | None = Field(
        default=None,
        description="Notes on which sources were used in NotebookLM",
    )
    confidence_scores: dict[str, float] | None = Field(
        default=None,
        description="Per-fact confidence scores (future metadata)",
    )
    annotations: str | None = Field(
        default=None,
        description="Researcher annotations (future metadata)",
    )
