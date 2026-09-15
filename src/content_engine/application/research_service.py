"""Research service — creates and validates research notes for brief generation.

Implements the Phase 06 research vertical slice:

    Topic.id
        -> ResearchService.create_research()
        -> validated ResearchNotes (with verification_status)
        -> ResearchService.is_ready_for_brief()
        -> handoff to Phase 07 brief generation

The service is provider-agnostic: it does not call any external provider.
Research input is assumed to come from human-performed NotebookLM work
or other manually collected sources (PRD §8.3, ARCHITECTURE §8).
"""

from uuid import UUID

from content_engine.domain.enums import ResearchVerificationStatus
from content_engine.domain.models import ResearchNotes


class ResearchService:
    """Create and validate research notes associated with a Topic.

    Research notes capture the minimum structured information needed to
    generate a content brief: key facts, terminology, examples, caveats,
    primary sources, and visual concepts. Source references are tracked
    in ``primary_sources``; ``Topic.source_refs`` is preserved separately
    and is not duplicated.

    No persistence is performed — the service operates in memory.
    """

    def create_research(
        self,
        topic_id: UUID,
        key_facts: list[str],
        terminology: list[str],
        examples: list[str],
        caveats: list[str],
        primary_sources: list[str],
        visual_concepts: list[str],
        verification_status: ResearchVerificationStatus = ResearchVerificationStatus.UNVERIFIED,
        notebooklm_session: str | None = None,
        source_notes: str | None = None,
        confidence_scores: dict[str, float] | None = None,
        annotations: str | None = None,
    ) -> ResearchNotes:
        """Create validated research notes for a topic.

        Args:
            topic_id: UUID of the Topic this research supports.
            key_facts: Factual points gathered during research.
            terminology: Domain terms and definitions captured.
            examples: Concrete examples gathered.
            caveats: Known limitations or edge cases.
            primary_sources: Source references (URLs or identifiers).
            visual_concepts: Visual directions tied to the topic.
            verification_status: Human verification status.
                Defaults to UNVERIFIED.
            notebooklm_session: Optional manual NotebookLM session reference.
            source_notes: Optional notes on sources used in NotebookLM.
            confidence_scores: Optional per-fact confidence scores.
            annotations: Optional researcher annotations.

        Returns:
            A validated ResearchNotes instance.
        """
        return ResearchNotes(
            topic_id=topic_id,
            key_facts=key_facts,
            terminology=terminology,
            examples=examples,
            caveats=caveats,
            primary_sources=primary_sources,
            visual_concepts=visual_concepts,
            verification_status=verification_status,
            notebooklm_session=notebooklm_session,
            source_notes=source_notes,
            confidence_scores=confidence_scores,
            annotations=annotations,
        )

    def is_ready_for_brief(self, research: ResearchNotes) -> bool:
        """Check if research is complete enough for brief generation.

        Research is ready when it has been human-verified and contains
        at least one key fact and one primary source reference.

        Args:
            research: The ResearchNotes to check.

        Returns:
            True if the research is ready for the next workflow stage.
        """
        return (
            research.verification_status == ResearchVerificationStatus.VERIFIED
            and len(research.key_facts) > 0
            and len(research.primary_sources) > 0
        )
