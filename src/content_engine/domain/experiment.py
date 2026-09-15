"""ExperimentRecord — the per-video record for the PRD's 10-15 video validation batch.

Field names deliberately mirror PRD FR-12/§11 terminology (production time,
regeneration count, incremental AI cost, audience metrics, quality scores)
so the connection to those requirements stays traceable.

Fields under "production accounting" are copied in from ``WorkflowState`` by
the CLI at record time (not derived here). Fields under "audience"/
"quality" are entered by a human after checking YouTube Studio and
reviewing the finished video — never fetched automatically; there is no
YouTube API integration in MVP.

``production_time_minutes`` is a human-entered value (Phase 12C decision):
it is NOT computed from any timestamp difference. A rough wall-clock
"started_at" (see ``WorkflowState``) usually includes idle time unrelated
to actual production effort, so the human enters what they judge
production time to actually be.

Gemini has no monetary cost on the free tier (PRD §8.2, §12): rather than
fabricate a currency figure, usage is recorded as request/token counts;
``incremental_ai_cost_notes`` is free text for the rare case a real,
paid cost is later incurred.
"""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from content_engine.domain.enums import Category
from content_engine.domain.models import utc_now


class QualityScores(BaseModel):
    """Human-entered 1-5 quality scores (PRD §11 — Quality).

    Every field is optional because scoring typically happens once, some
    time after publication, not incrementally with each edit. ``None``
    means "not yet scored," never "scored zero." Never derived/computed.
    """

    accuracy: int | None = Field(default=None, ge=1, le=5)
    clarity: int | None = Field(default=None, ge=1, le=5)
    hook: int | None = Field(default=None, ge=1, le=5)
    visual_quality: int | None = Field(default=None, ge=1, le=5)
    pacing: int | None = Field(default=None, ge=1, le=5)
    originality: int | None = Field(default=None, ge=1, le=5)
    overall: int | None = Field(default=None, ge=1, le=5)


class ExperimentRecord(BaseModel):
    """The FR-12/§11 per-video record for one Topic, keyed by ``topic_id``.

    Re-running ``content experiment record`` for the same topic upserts
    this record rather than creating a new one — audience metrics in
    particular are typically unavailable at packaging time and get filled
    in later, once YouTube has accumulated views.
    """

    topic_id: UUID = Field(description="The Topic this record reports on")
    title: str = Field(min_length=1, description="Topic title, denormalized for readability")
    category: Category = Field(description="Content category, denormalized for readability")

    production_id: UUID | None = Field(default=None)
    review_id: UUID | None = Field(default=None)
    package_id: UUID | None = Field(default=None)

    # --- Production metrics (PRD FR-12 / §11) ---
    production_time_minutes: float | None = Field(
        default=None,
        ge=0,
        description="Human-entered production time in minutes. Never auto-computed.",
    )
    regeneration_count: int = Field(
        default=0,
        ge=0,
        description="Total regenerations across brief/script/storyboard/assemble",
    )
    gemini_requests_used: int = Field(default=0, ge=0)
    gemini_tokens_used: int = Field(default=0, ge=0)
    flow_credits_used: int = Field(default=0, ge=0)
    incremental_ai_cost_notes: str | None = Field(
        default=None,
        description="Free-text monetary cost note. Left unset while on the free tier.",
    )

    # --- Audience metrics (PRD FR-12 / §11) — manual, no YouTube API ---
    publish_date: date | None = Field(default=None)
    views: int | None = Field(default=None, ge=0)
    average_view_duration_seconds: float | None = Field(default=None, ge=0)
    percent_viewed: float | None = Field(default=None, ge=0, le=100)
    likes: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    shares: int | None = Field(default=None, ge=0)
    subscribers_gained: int | None = Field(
        default=None, description="May be negative if net subscribers were lost"
    )

    # --- Quality scores (PRD §11) — human-entered, never derived ---
    quality: QualityScores = Field(default_factory=QualityScores)

    notes: str | None = Field(default=None, description="Free-text lessons learned")

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
