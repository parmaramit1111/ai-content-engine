"""Filesystem-based persistence for Phase 06-11 domain artifacts (ARCHITECTURE §12, §16).

Provides the minimal, provider-agnostic storage layer needed so validated
domain models (Topic, ResearchNotes, ContentBrief, Script, Storyboard,
Review) can be persisted and reloaded between human-in-the-loop workflow
steps (PRD §6; ARCHITECTURE §12 lists ``storage/filesystem.py``).

Each model is serialized via its own ``model_dump_json``/
``model_validate_json`` (JSON, matching the round-trip convention already
used in the Phase 06-11 model tests) — field mappings are never
hand-duplicated here, so UUIDs and timestamps round-trip exactly as the
model itself defines.

No provider, budget, media, or CLI dependency. Only the small structured
artifacts named above are ever written here — never secrets (API keys are
environment-only, per ARCHITECTURE §17) and never generated media (video/
audio live under ``assets/``, not ``content/``).
"""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel, ValidationError

from content_engine.domain.experiment import ExperimentRecord
from content_engine.domain.models import (
    ContentBrief,
    Production,
    PublicationPackage,
    ResearchNotes,
    Review,
    Script,
    Storyboard,
    Topic,
)
from content_engine.domain.workflow import WorkflowState

_ModelT = TypeVar("_ModelT", bound=BaseModel)


class StorageError(Exception):
    """Base class for content storage errors."""


class ArtifactNotFoundError(StorageError):
    """Raised when a requested artifact file does not exist or is not a regular file."""


class ArtifactCorruptError(StorageError):
    """Raised when an artifact file's contents cannot be parsed into its model."""


class ContentStore:
    """Persist and reload Phase 06-11 domain artifacts as JSON files.

    Each instance is stored as its own file, named by its stable UUID
    (``<id>.json``), under a fixed subdirectory per model type::

        <content_root>/topics/<id>.json
        <content_root>/research/<id>.json
        <content_root>/briefs/<id>.json
        <content_root>/scripts/<id>.json
        <content_root>/storyboards/<id>.json
        <content_root>/reviews/<id>.json
        <content_root>/productions/<id>.json
        <content_root>/packages/<id>.json
        <content_root>/workflow/<topic_id>.json
        <content_root>/experiments/<topic_id>.json

    ``productions`` and ``packages`` extend the original Phase 12 minimum
    (Topic, ResearchNotes, ContentBrief, Script, Storyboard, Review): the
    Phase 12B CLI needs a ``Production`` reloadable by id so
    ``content review create`` can hand a real ``Production`` to
    ``ReviewService.create_review`` across separate CLI invocations without
    fabricating placeholder data, and a persisted ``PublicationPackage``
    gives the final workflow artifact a durable record. This reuses the
    same ``ContentStore``, not a second storage mechanism.

    ``workflow`` and ``experiments`` (Phase 12C) are keyed by ``topic_id``
    instead of the model's own ``id`` — there is exactly one
    ``WorkflowState`` and one ``ExperimentRecord`` per Topic, and
    ``topic_id`` is the one identifier a human running the CLI always has
    on hand. This is still the same generic ``_save``/``_load`` machinery;
    only the id used as the filename differs.

    Subdirectories are created automatically on first write. Saving an id
    that already has a file overwrites it — there is no separate "update"
    operation, matching how these models are otherwise treated as
    immutable-and-replaced (e.g. ``ReviewService`` returning a new
    ``Review`` via ``model_copy`` rather than mutating in place).

    Args:
        content_root: Root directory for all content artifacts (e.g. ``./content``).
    """

    def __init__(self, content_root: Path):
        self._root = content_root

    # ---- Topic ----

    def save_topic(self, topic: Topic) -> Path:
        return self._save(topic, "topics", topic.id)

    def load_topic(self, topic_id: UUID) -> Topic:
        return self._load(Topic, "topics", topic_id, "Topic")

    # ---- ResearchNotes ----

    def save_research_notes(self, research: ResearchNotes) -> Path:
        return self._save(research, "research", research.id)

    def load_research_notes(self, research_id: UUID) -> ResearchNotes:
        return self._load(ResearchNotes, "research", research_id, "ResearchNotes")

    # ---- ContentBrief ----

    def save_content_brief(self, brief: ContentBrief) -> Path:
        return self._save(brief, "briefs", brief.id)

    def load_content_brief(self, brief_id: UUID) -> ContentBrief:
        return self._load(ContentBrief, "briefs", brief_id, "ContentBrief")

    # ---- Script ----

    def save_script(self, script: Script) -> Path:
        return self._save(script, "scripts", script.id)

    def load_script(self, script_id: UUID) -> Script:
        return self._load(Script, "scripts", script_id, "Script")

    # ---- Storyboard ----

    def save_storyboard(self, storyboard: Storyboard) -> Path:
        return self._save(storyboard, "storyboards", storyboard.id)

    def load_storyboard(self, storyboard_id: UUID) -> Storyboard:
        return self._load(Storyboard, "storyboards", storyboard_id, "Storyboard")

    # ---- Review ----

    def save_review(self, review: Review) -> Path:
        return self._save(review, "reviews", review.id)

    def load_review(self, review_id: UUID) -> Review:
        return self._load(Review, "reviews", review_id, "Review")

    # ---- Production ----

    def save_production(self, production: Production) -> Path:
        return self._save(production, "productions", production.id)

    def load_production(self, production_id: UUID) -> Production:
        return self._load(Production, "productions", production_id, "Production")

    # ---- PublicationPackage ----

    def save_publication_package(self, package: PublicationPackage) -> Path:
        return self._save(package, "packages", package.id)

    def load_publication_package(self, package_id: UUID) -> PublicationPackage:
        return self._load(PublicationPackage, "packages", package_id, "PublicationPackage")

    # ---- WorkflowState ----

    def save_workflow_state(self, state: WorkflowState) -> Path:
        return self._save(state, "workflow", state.topic_id)

    def load_workflow_state(self, topic_id: UUID) -> WorkflowState:
        return self._load(WorkflowState, "workflow", topic_id, "WorkflowState")

    # ---- ExperimentRecord ----

    def save_experiment_record(self, record: ExperimentRecord) -> Path:
        return self._save(record, "experiments", record.topic_id)

    def load_experiment_record(self, topic_id: UUID) -> ExperimentRecord:
        return self._load(ExperimentRecord, "experiments", topic_id, "ExperimentRecord")

    def list_experiment_records(self) -> list[ExperimentRecord]:
        """Return every persisted ExperimentRecord, for `experiment list`/`export-csv`.

        Reuses ``load_experiment_record`` per file so a corrupt record
        raises the same ``ArtifactCorruptError`` (naming the exact path) as
        loading it directly would.
        """
        directory = self._root / "experiments"
        if not directory.is_dir():
            return []
        return [
            self.load_experiment_record(UUID(path.stem))
            for path in sorted(directory.glob("*.json"))
        ]

    # ---- Shared helpers ----

    def _path_for(self, subdir: str, artifact_id: UUID) -> Path:
        return self._root / subdir / f"{artifact_id}.json"

    def _save(self, model: BaseModel, subdir: str, artifact_id: UUID) -> Path:
        path = self._path_for(subdir, artifact_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(model.model_dump_json(indent=2), encoding="utf-8")
        return path

    def _load(
        self,
        model_cls: type[_ModelT],
        subdir: str,
        artifact_id: UUID,
        kind: str,
    ) -> _ModelT:
        path = self._path_for(subdir, artifact_id)
        if not path.is_file():
            raise ArtifactNotFoundError(f"{kind} artifact not found: {path}")

        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ArtifactNotFoundError(f"Failed to read {kind} artifact {path}: {exc}") from exc

        try:
            return model_cls.model_validate_json(raw)
        except ValidationError as exc:
            raise ArtifactCorruptError(f"Malformed {kind} artifact at {path}: {exc}") from exc
