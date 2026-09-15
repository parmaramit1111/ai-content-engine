"""Per-topic operational bookkeeping for the Phase 12 CLI (Phase 12C).

``WorkflowState`` is deliberately NOT a workflow engine or state machine: it
never validates transitions, never gates a command, and is never seen by
any Phase 06-11 service. It is a flat lookup/accumulator that the CLI reads
before falling back to a default ID and writes after a successful command,
so a human running the E2E workflow across separate CLI invocations
doesn't have to re-type every UUID/path by hand.

Timestamps here are for operational visibility only (``content workflow
show``). They must never be used to compute
``ExperimentRecord.production_time_minutes`` — production time is an
explicitly human-recorded metric (Phase 12C decision), never derived from
``completed_at - started_at`` or any other timestamp arithmetic.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from content_engine.domain.models import utc_now


class WorkflowState(BaseModel):
    """Per-topic pointer/accumulator record, keyed by ``topic_id``.

    One instance per Topic. Every field beyond ``topic_id`` starts empty/
    zero because a fresh workflow has nothing recorded yet; each CLI
    command that succeeds fills in exactly the field(s) it owns.
    """

    topic_id: UUID = Field(description="The Topic this workflow state tracks")

    research_id: UUID | None = Field(default=None)
    brief_id: UUID | None = Field(default=None)
    script_id: UUID | None = Field(default=None)
    storyboard_id: UUID | None = Field(default=None)
    production_id: UUID | None = Field(default=None)
    review_id: UUID | None = Field(default=None)
    package_id: UUID | None = Field(default=None)

    asset_manifest_path: str | None = Field(
        default=None, description="Last asset manifest file used for this storyboard"
    )
    audio_path: str | None = Field(default=None, description="Last narration/audio path used")
    audio_source: str | None = Field(default=None, description="Last narration/audio provenance")
    audio_provider: str | None = Field(default=None, description="Last narration/audio tool")

    brief_regenerations: int = Field(
        default=0, ge=0, description="Count of brief generations beyond the first"
    )
    script_regenerations: int = Field(
        default=0, ge=0, description="Count of script generations beyond the first"
    )
    storyboard_regenerations: int = Field(
        default=0, ge=0, description="Count of storyboard generations beyond the first"
    )
    assemble_regenerations: int = Field(
        default=0, ge=0, description="Count of assemble runs beyond the first"
    )

    gemini_requests_used: int = Field(
        default=0, ge=0, description="Cumulative Gemini requests attributed to this topic"
    )
    gemini_tokens_used: int = Field(
        default=0, ge=0, description="Cumulative Gemini tokens attributed to this topic"
    )
    flow_credits_used: int = Field(
        default=0, ge=0, description="Cumulative human-reported Google Flow credits"
    )

    started_at: datetime = Field(
        default_factory=utc_now, description="Operational visibility only — not production time"
    )
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = Field(
        default=None, description="Set when a PublicationPackage is created; visibility only"
    )
