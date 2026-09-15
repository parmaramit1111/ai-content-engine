"""Thin Typer CLI orchestrating the Phase 06-11 services (ARCHITECTURE §12, §14; Phase 12 task).

This module contains no business logic of its own. Every command:

    1. Loads whatever artifacts it needs via ``ContentStore``.
    2. Calls exactly one existing application service (``ResearchService``,
       ``BriefService``, ``ScriptService``, ``StoryboardService``,
       ``AssetService``, ``VideoAssemblyService``, ``ReviewService``) or the
       ``BudgetTracker`` directly.
    3. Saves the resulting artifact via ``ContentStore`` (where supported)
       and prints identifiers/paths.

Human-in-the-loop boundaries (NotebookLM, Google Flow, YouTube) are never
automated here — the CLI only records/validates what a human has already
produced (PRD §8; ARCHITECTURE §6, §8, §10). Gemini calls always go through
the existing ``GeminiProvider`` + ``BudgetTracker`` wiring, so the local
safety budget can never be bypassed (PRD §8.2, §9).

``Asset``, ``AudioTrack`` are transient — a single ``assemble`` invocation
consumes them immediately and nothing downstream needs to reload them, so
they are intentionally not added to ``ContentStore``. ``Production`` and
``PublicationPackage`` are persisted (see ``content_engine.storage.filesystem``)
so ``review create``/``package create`` can be run as separate CLI
invocations without fabricating placeholder data.

``WorkflowState`` (Phase 12C) is a per-topic bookkeeping record, not a
workflow engine: commands read it only to fall back to a previously
recorded ID/path when the corresponding ``--*-id``/``--manifest``/
``--audio-*`` option is omitted, and write to it only to record the IDs,
regeneration counts, and Gemini/Flow usage a successful call just
produced. Explicit CLI values always take precedence, and no command
consults it at all unless ``--topic-id`` is supplied — omitting
``--topic-id`` reproduces exact Phase 12B behavior. It never validates
ordering or blocks a command.

``ExperimentRecord``/``QualityScores`` (Phase 12C) hold the PRD FR-12/§11
per-video metrics for the 10-15 video validation batch. Production-side
fields are copied in from ``WorkflowState`` by ``experiment record``;
audience/quality fields and ``production_time_minutes`` are always
human-entered — never derived from any timestamp or fabricated.
"""

from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path
from typing import Any, NoReturn
from uuid import UUID

import typer
from pydantic import BaseModel, ValidationError

from content_engine.application.asset_service import AssetService, AssetServiceError
from content_engine.application.brief_service import BriefService, BriefServiceError
from content_engine.application.research_service import ResearchService
from content_engine.application.review_service import ReviewService, ReviewServiceError
from content_engine.application.script_service import ScriptService, ScriptServiceError
from content_engine.application.storyboard_service import (
    StoryboardService,
    StoryboardServiceError,
)
from content_engine.application.video_assembly_service import (
    VideoAssemblyService,
    VideoAssemblyServiceError,
)
from content_engine.budgets.models import ProviderBudget
from content_engine.budgets.tracker import (
    BudgetExceededError,
    BudgetTracker,
    load_budgets_from_config,
)
from content_engine.config import AppSettings, BudgetConfigError, get_budget_settings, get_settings
from content_engine.domain.enums import (
    Category,
    Difficulty,
    ResearchVerificationStatus,
    ReviewCategory,
)
from content_engine.domain.experiment import ExperimentRecord
from content_engine.domain.models import (
    Asset,
    AudioTrack,
    ChecklistItem,
    Storyboard,
    Topic,
    utc_now,
)
from content_engine.domain.workflow import WorkflowState
from content_engine.providers.exceptions import (
    ProviderAPIError,
    ProviderConfigurationError,
    ProviderQuotaError,
)
from content_engine.providers.gemini.provider import GeminiProvider
from content_engine.storage import ArtifactNotFoundError, ContentStore, StorageError


class CLIError(Exception):
    """Raised for CLI-level input/configuration problems (not a domain/service error)."""


# Every exception type a command body may let escape from a service/storage/
# provider/config call. Caught explicitly (never a bare ``except Exception``)
# so unexpected bugs still surface as real tracebacks.
_KNOWN_ERRORS = (
    CLIError,
    StorageError,
    BriefServiceError,
    ScriptServiceError,
    StoryboardServiceError,
    AssetServiceError,
    VideoAssemblyServiceError,
    ReviewServiceError,
    ProviderConfigurationError,
    ProviderQuotaError,
    ProviderAPIError,
    BudgetExceededError,
    BudgetConfigError,
    ValidationError,
)

app = typer.Typer(name="content", help="Local, file-based AI content production workflow.")
topic_app = typer.Typer(help="Manage Topics.")
research_app = typer.Typer(help="Record and verify human-in-the-loop research (NotebookLM).")
brief_app = typer.Typer(help="Generate ContentBriefs via Gemini.")
script_app = typer.Typer(help="Generate Scripts via Gemini.")
storyboard_app = typer.Typer(help="Generate Storyboards via Gemini.")
asset_app = typer.Typer(help="Import/validate human-generated Google Flow clips.")
audio_app = typer.Typer(help="Import human-supplied narration/audio.")
review_app = typer.Typer(help="Human review gate for a Production.")
package_app = typer.Typer(help="Package an approved Review for manual publication.")
budget_app = typer.Typer(help="Inspect local provider budget status.")
workflow_app = typer.Typer(help="Inspect per-topic WorkflowState.")
experiment_app = typer.Typer(help="Record/report PRD FR-12 experiment metrics.")

app.add_typer(topic_app, name="topic")
app.add_typer(research_app, name="research")
app.add_typer(brief_app, name="brief")
app.add_typer(script_app, name="script")
app.add_typer(storyboard_app, name="storyboard")
app.add_typer(asset_app, name="asset")
app.add_typer(audio_app, name="audio")
app.add_typer(review_app, name="review")
app.add_typer(package_app, name="package")
app.add_typer(budget_app, name="budget")
app.add_typer(workflow_app, name="workflow")
app.add_typer(experiment_app, name="experiment")


# --- Shared wiring helpers (composition-root glue, not business logic) ---


def _fail(message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code=1)


def _content_root(override: Path | None) -> Path:
    return override if override is not None else Path(get_settings().content_root)


def _asset_root(override: Path | None) -> Path:
    return override if override is not None else Path(get_settings().asset_root)


def _store(content_root: Path | None) -> ContentStore:
    return ContentStore(_content_root(content_root))


def _build_gemini_provider(settings: AppSettings) -> tuple[GeminiProvider, BudgetTracker]:
    """Wire a GeminiProvider from configured settings + the budget YAML.

    Never bypasses budget enforcement: the returned provider always checks
    ``BudgetTracker`` before every call (ARCHITECTURE §5, §7). The tracker
    is also returned so callers can read ``usage_records()`` afterward to
    accumulate Gemini usage into ``WorkflowState`` (Phase 12C) — a fresh
    tracker is built per CLI invocation, so every record in it after a
    single ``generate()`` call belongs to that call; no filtering needed.
    """
    if not settings.gemini_model:
        raise CLIError("GEMINI_MODEL is not configured; set it via environment or .env")

    budget_config = get_budget_settings(settings.budget_config)
    budgets = load_budgets_from_config(budget_config)
    tracker = BudgetTracker(budgets)
    provider = GeminiProvider(
        api_key=settings.gemini_api_key, model=settings.gemini_model, tracker=tracker
    )
    return provider, tracker


def _sum_gemini_usage(tracker: BudgetTracker) -> tuple[int, int]:
    """Sum a tracker's usage records into (requests, tokens) totals."""
    records = tracker.usage_records()
    requests = sum(u.units for u in records if u.unit_type == "requests")
    tokens = sum(u.units for u in records if u.unit_type == "tokens")
    return requests, tokens


def _load_or_create_workflow_state(store: ContentStore, topic_id: UUID) -> WorkflowState:
    """Load a topic's WorkflowState, or start a fresh one if none exists yet.

    Only ``ArtifactNotFoundError`` is treated as "start fresh" — a corrupt
    existing file (``ArtifactCorruptError``) must never be silently
    replaced, so it propagates as a real error.
    """
    try:
        return store.load_workflow_state(topic_id)
    except ArtifactNotFoundError:
        return WorkflowState(topic_id=topic_id)


def _update_workflow_state(store: ContentStore, state: WorkflowState, **updates: Any) -> None:
    """Apply field updates, bump ``updated_at``, and persist. Bookkeeping only."""
    updated = state.model_copy(update={**updates, "updated_at": utc_now()})
    store.save_workflow_state(updated)


def _resolve_id(explicit: UUID | None, state_value: UUID | None, *, flag: str, label: str) -> UUID:
    """Explicit CLI value always wins; otherwise fall back to WorkflowState."""
    if explicit is not None:
        return explicit
    if state_value is not None:
        return state_value
    raise CLIError(f"{label} not supplied and not found in WorkflowState; pass {flag} explicitly")


def _resolve_path(explicit: Path | None, state_value: str | None, *, flag: str, label: str) -> Path:
    """Explicit CLI value always wins; otherwise fall back to WorkflowState."""
    if explicit is not None:
        return explicit
    if state_value is not None:
        return Path(state_value)
    raise CLIError(f"{label} not supplied and not found in WorkflowState; pass {flag} explicitly")


def _dimensions_for(budget: ProviderBudget) -> list[str]:
    """Return the usage dimensions actually configured for a provider budget.

    ``requests`` is always checked. ``tokens`` (or any other per-dimension
    key) is only checked when the config actually populated it — otherwise
    ``BudgetTracker`` would silently fall back to the single-value
    ``local_budget`` field and misreport an unrelated dimension as budgeted
    (e.g. reporting a Flow "tokens" budget that was never configured).
    """
    dims = {"requests", *budget.local_budget_by_unit_type, *budget.official_limit_by_unit_type}
    return sorted(dims)


def _read_json_file(path: Path) -> Any:
    if not path.is_file():
        raise CLIError(f"File not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CLIError(f"Failed to read {path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CLIError(f"Invalid JSON in {path}: {exc}") from exc


def _parse_checklist(path: Path) -> dict[ReviewCategory, ChecklistItem]:
    raw = _read_json_file(path)
    if not isinstance(raw, dict):
        raise CLIError(f"Checklist file must contain a JSON object: {path}")

    checklist: dict[ReviewCategory, ChecklistItem] = {}
    for key, value in raw.items():
        try:
            category = ReviewCategory(key)
        except ValueError as exc:
            raise CLIError(f"Unknown review category '{key}' in {path}") from exc
        try:
            checklist[category] = ChecklistItem.model_validate(value)
        except ValidationError as exc:
            raise CLIError(f"Invalid checklist entry for '{key}' in {path}: {exc}") from exc
    return checklist


class AssetManifestEntry(BaseModel):
    """One line of an asset manifest file (CLI input contract, not a domain model)."""

    scene_number: int
    path: str
    source: str
    provider: str | None = None
    flow_credits_used: int | None = None
    metadata: dict[str, Any] | None = None


def _parse_asset_manifest(manifest_path: Path) -> list[AssetManifestEntry]:
    raw = _read_json_file(manifest_path)
    if not isinstance(raw, list):
        raise CLIError(f"Asset manifest must be a JSON array: {manifest_path}")
    try:
        return [AssetManifestEntry.model_validate(item) for item in raw]
    except ValidationError as exc:
        raise CLIError(f"Invalid asset manifest entry in {manifest_path}: {exc}") from exc


def _import_assets_from_manifest(
    asset_service: AssetService, storyboard: Storyboard, manifest_path: Path
) -> list[Asset]:
    entries = _parse_asset_manifest(manifest_path)
    return [
        asset_service.import_asset(
            storyboard,
            entry.scene_number,
            entry.path,
            source=entry.source,
            provider=entry.provider,
            flow_credits_used=entry.flow_credits_used,
            metadata=entry.metadata,
        )
        for entry in entries
    ]


def _maybe_import_audio(
    assembly_service: VideoAssemblyService,
    storyboard: Storyboard,
    audio_path: str | None,
    audio_source: str | None,
    audio_provider: str | None,
) -> AudioTrack | None:
    if audio_path is None:
        return None
    if audio_source is None:
        raise CLIError("--audio-source is required when --audio-path is supplied")
    return assembly_service.import_audio_track(
        storyboard, audio_path, source=audio_source, provider=audio_provider
    )


# --- topic ---


@topic_app.command("create")
def topic_create(
    title: str = typer.Option(..., help="Topic title"),
    category: Category = typer.Option(..., help="Content category"),
    audience: str = typer.Option(..., help="Target audience"),
    difficulty: Difficulty = typer.Option(..., help="Target difficulty"),
    hook: str = typer.Option(..., help="Opening hook for the video"),
    source_ref: list[str] = typer.Option([], help="Source reference (repeatable)"),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
) -> None:
    """Create a Topic and persist it via ContentStore.

    Also creates an empty WorkflowState for the new topic (Phase 12C) so
    later commands can resolve/record IDs against it via ``--topic-id``.
    Topic.status is never touched here or by any other command.
    """
    try:
        topic = Topic(
            title=title,
            category=category,
            audience=audience,
            difficulty=difficulty,
            hook=hook,
            source_refs=list(source_ref),
        )
        store = _store(content_root)
        path = store.save_topic(topic)
        store.save_workflow_state(WorkflowState(topic_id=topic.id))
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(f"topic_id={topic.id}")
    typer.echo(f"path={path}")


# --- research ---


@research_app.command("create")
def research_create(
    topic_id: UUID = typer.Option(..., help="Topic this research supports"),
    key_fact: list[str] = typer.Option([], help="Factual point (repeatable)"),
    terminology: list[str] = typer.Option([], help="Domain term/definition (repeatable)"),
    example: list[str] = typer.Option([], help="Concrete example (repeatable)"),
    caveat: list[str] = typer.Option([], help="Known limitation/edge case (repeatable)"),
    primary_source: list[str] = typer.Option([], help="Source reference (repeatable)"),
    visual_concept: list[str] = typer.Option([], help="Visual direction (repeatable)"),
    notebooklm_session: str | None = typer.Option(None, help="Manual NotebookLM session reference"),
    source_notes: str | None = typer.Option(None),
    annotations: str | None = typer.Option(None),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
) -> None:
    """Record human-performed NotebookLM research. Always starts UNVERIFIED."""
    try:
        store = _store(content_root)
        topic = store.load_topic(topic_id)
        research = ResearchService().create_research(
            topic_id=topic.id,
            key_facts=list(key_fact),
            terminology=list(terminology),
            examples=list(example),
            caveats=list(caveat),
            primary_sources=list(primary_source),
            visual_concepts=list(visual_concept),
            notebooklm_session=notebooklm_session,
            source_notes=source_notes,
            annotations=annotations,
        )
        path = store.save_research_notes(research)
        state = _load_or_create_workflow_state(store, topic.id)
        _update_workflow_state(store, state, research_id=research.id)
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(f"research_id={research.id}")
    typer.echo(f"verification_status={research.verification_status.value}")
    typer.echo(f"path={path}")


@research_app.command("verify")
def research_verify(
    research_id: UUID | None = typer.Option(
        None, help="Falls back to WorkflowState.research_id if omitted (requires --topic-id)"
    ),
    topic_id: UUID | None = typer.Option(
        None, help="Optional: resolve missing --research-id and update WorkflowState"
    ),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
) -> None:
    """Record that a human has verified previously-recorded research."""
    try:
        store = _store(content_root)
        state = _load_or_create_workflow_state(store, topic_id) if topic_id is not None else None
        resolved_research_id = _resolve_id(
            research_id,
            state.research_id if state else None,
            flag="--research-id",
            label="research_id",
        )

        research = store.load_research_notes(resolved_research_id)
        verified = research.model_copy(
            update={
                "verification_status": ResearchVerificationStatus.VERIFIED,
                "updated_at": utc_now(),
            }
        )
        path = store.save_research_notes(verified)

        if state is not None:
            _update_workflow_state(store, state, research_id=resolved_research_id)

        ready = ResearchService().is_ready_for_brief(verified)
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(f"research_id={verified.id}")
    typer.echo(f"verification_status={verified.verification_status.value}")
    typer.echo(f"ready_for_brief={ready}")
    typer.echo(f"path={path}")


# --- brief ---


@brief_app.command("generate")
def brief_generate(
    topic_id: UUID = typer.Option(..., help="Also used to look up/update WorkflowState"),
    research_id: UUID | None = typer.Option(
        None, help="Falls back to WorkflowState.research_id if omitted"
    ),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
) -> None:
    """Generate a ContentBrief from a Topic + verified ResearchNotes via Gemini."""
    try:
        store = _store(content_root)
        topic = store.load_topic(topic_id)
        state = _load_or_create_workflow_state(store, topic_id)
        resolved_research_id = _resolve_id(
            research_id, state.research_id, flag="--research-id", label="research_id"
        )

        research = store.load_research_notes(resolved_research_id)
        if not ResearchService().is_ready_for_brief(research):
            raise CLIError(
                f"Research {research.id} is not ready for brief generation: "
                "must be VERIFIED with at least one key fact and one primary source"
            )
        provider, tracker = _build_gemini_provider(get_settings())
        brief = asyncio.run(BriefService(provider).generate_brief(topic, research))
        path = store.save_content_brief(brief)

        requests_delta, tokens_delta = _sum_gemini_usage(tracker)
        _update_workflow_state(
            store,
            state,
            research_id=resolved_research_id,
            brief_id=brief.id,
            brief_regenerations=state.brief_regenerations + (1 if state.brief_id else 0),
            gemini_requests_used=state.gemini_requests_used + requests_delta,
            gemini_tokens_used=state.gemini_tokens_used + tokens_delta,
        )
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(f"brief_id={brief.id}")
    typer.echo(f"path={path}")


# --- script ---


@script_app.command("generate")
def script_generate(
    brief_id: UUID | None = typer.Option(
        None, help="Falls back to WorkflowState.brief_id if omitted (requires --topic-id)"
    ),
    topic_id: UUID | None = typer.Option(
        None, help="Optional: resolve missing --brief-id and update WorkflowState"
    ),
    version: int = typer.Option(1, min=1),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
) -> None:
    """Generate a Script from a ContentBrief via Gemini."""
    try:
        store = _store(content_root)
        state = _load_or_create_workflow_state(store, topic_id) if topic_id is not None else None
        resolved_brief_id = _resolve_id(
            brief_id, state.brief_id if state else None, flag="--brief-id", label="brief_id"
        )

        brief = store.load_content_brief(resolved_brief_id)
        provider, tracker = _build_gemini_provider(get_settings())
        script = asyncio.run(ScriptService(provider).generate_script(brief, version=version))
        path = store.save_script(script)

        if state is not None:
            requests_delta, tokens_delta = _sum_gemini_usage(tracker)
            _update_workflow_state(
                store,
                state,
                brief_id=resolved_brief_id,
                script_id=script.id,
                script_regenerations=state.script_regenerations + (1 if state.script_id else 0),
                gemini_requests_used=state.gemini_requests_used + requests_delta,
                gemini_tokens_used=state.gemini_tokens_used + tokens_delta,
            )
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(f"script_id={script.id}")
    typer.echo(f"path={path}")


# --- storyboard ---


@storyboard_app.command("generate")
def storyboard_generate(
    script_id: UUID | None = typer.Option(
        None, help="Falls back to WorkflowState.script_id if omitted (requires --topic-id)"
    ),
    brief_id: UUID | None = typer.Option(
        None, help="Falls back to WorkflowState.brief_id if omitted (requires --topic-id)"
    ),
    topic_id: UUID | None = typer.Option(
        None, help="Optional: resolve missing IDs and update WorkflowState"
    ),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
) -> None:
    """Generate a Storyboard (enriched visual prompts) from a Script + ContentBrief via Gemini."""
    try:
        store = _store(content_root)
        state = _load_or_create_workflow_state(store, topic_id) if topic_id is not None else None
        resolved_script_id = _resolve_id(
            script_id, state.script_id if state else None, flag="--script-id", label="script_id"
        )
        resolved_brief_id = _resolve_id(
            brief_id, state.brief_id if state else None, flag="--brief-id", label="brief_id"
        )

        script = store.load_script(resolved_script_id)
        brief = store.load_content_brief(resolved_brief_id)
        provider, tracker = _build_gemini_provider(get_settings())
        storyboard = asyncio.run(StoryboardService(provider).generate_storyboard(script, brief))
        path = store.save_storyboard(storyboard)

        if state is not None:
            requests_delta, tokens_delta = _sum_gemini_usage(tracker)
            _update_workflow_state(
                store,
                state,
                script_id=resolved_script_id,
                brief_id=resolved_brief_id,
                storyboard_id=storyboard.id,
                storyboard_regenerations=(
                    state.storyboard_regenerations + (1 if state.storyboard_id else 0)
                ),
                gemini_requests_used=state.gemini_requests_used + requests_delta,
                gemini_tokens_used=state.gemini_tokens_used + tokens_delta,
            )
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(f"storyboard_id={storyboard.id}")
    typer.echo(f"path={path}")


# --- asset ---


@asset_app.command("import")
def asset_import(
    storyboard_id: UUID = typer.Option(...),
    scene_number: int = typer.Option(...),
    path: str = typer.Option(..., help="Path to a human-generated Google Flow clip"),
    source: str = typer.Option(..., help="Provenance, e.g. 'google_flow'"),
    provider: str | None = typer.Option(None, help="Specific model, e.g. 'veo-3.1-fast'"),
    flow_credits_used: int | None = typer.Option(None, help="Human-reported Flow credits spent"),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
    asset_root: Path | None = typer.Option(None, help="Override the configured asset root"),
) -> None:
    """Validate one human-generated clip for one storyboard scene.

    Not persisted (Asset is transient) — prints the validated Asset as JSON
    so it can be recorded in an asset manifest for ``asset validate``/
    ``assemble``.
    """
    try:
        store = _store(content_root)
        storyboard = store.load_storyboard(storyboard_id)
        service = AssetService(_asset_root(asset_root))
        asset = service.import_asset(
            storyboard,
            scene_number,
            path,
            source=source,
            provider=provider,
            flow_credits_used=flow_credits_used,
        )
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(asset.model_dump_json(indent=2))


@asset_app.command("validate")
def asset_validate(
    storyboard_id: UUID | None = typer.Option(
        None, help="Falls back to WorkflowState.storyboard_id if omitted (requires --topic-id)"
    ),
    manifest: Path | None = typer.Option(
        None, help="Falls back to WorkflowState.asset_manifest_path if omitted"
    ),
    topic_id: UUID | None = typer.Option(
        None, help="Optional: resolve missing IDs and remember the manifest path"
    ),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
    asset_root: Path | None = typer.Option(None, help="Override the configured asset root"),
) -> None:
    """Validate an entire manifest of clips against a Storyboard's scene coverage."""
    try:
        store = _store(content_root)
        state = _load_or_create_workflow_state(store, topic_id) if topic_id is not None else None
        resolved_storyboard_id = _resolve_id(
            storyboard_id,
            state.storyboard_id if state else None,
            flag="--storyboard-id",
            label="storyboard_id",
        )
        resolved_manifest = _resolve_path(
            manifest,
            state.asset_manifest_path if state else None,
            flag="--manifest",
            label="manifest",
        )

        storyboard = store.load_storyboard(resolved_storyboard_id)
        service = AssetService(_asset_root(asset_root))
        assets = _import_assets_from_manifest(service, storyboard, resolved_manifest)
        covered = service.all_scenes_covered(storyboard, assets)

        if state is not None:
            _update_workflow_state(
                store,
                state,
                storyboard_id=resolved_storyboard_id,
                asset_manifest_path=str(resolved_manifest),
            )
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(f"assets_validated={len(assets)}")
    typer.echo(f"scenes_covered={covered}")
    if not covered:
        expected = {scene.number for scene in storyboard.scenes}
        found = {asset.scene_number for asset in assets}
        missing = sorted(expected - found)
        typer.echo(f"missing_scenes={missing}", err=True)
        raise typer.Exit(code=1)


# --- audio ---


@audio_app.command("import")
def audio_import(
    storyboard_id: UUID = typer.Option(...),
    path: str = typer.Option(..., help="Path to human-supplied narration/audio"),
    source: str = typer.Option(..., help="Provenance, e.g. 'human_narration'"),
    provider: str | None = typer.Option(None, help="Specific tool, e.g. 'google_tts'"),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
    asset_root: Path | None = typer.Option(None, help="Override the configured asset root"),
) -> None:
    """Validate a human-supplied narration/audio file for a Storyboard.

    Not persisted (AudioTrack is transient) — prints the validated
    AudioTrack as JSON; pass the same path/source/provider to ``assemble``.
    """
    try:
        store = _store(content_root)
        storyboard = store.load_storyboard(storyboard_id)
        service = VideoAssemblyService(_asset_root(asset_root))
        audio_track = service.import_audio_track(storyboard, path, source=source, provider=provider)
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(audio_track.model_dump_json(indent=2))


# --- assemble ---


@app.command("assemble")
def assemble(
    storyboard_id: UUID | None = typer.Option(
        None, help="Falls back to WorkflowState.storyboard_id if omitted (requires --topic-id)"
    ),
    manifest: Path | None = typer.Option(
        None, help="Falls back to WorkflowState.asset_manifest_path if omitted"
    ),
    audio_path: str | None = typer.Option(
        None, help="Falls back to WorkflowState.audio_path if omitted"
    ),
    audio_source: str | None = typer.Option(
        None, help="Required alongside --audio-path (or falls back to WorkflowState.audio_source)"
    ),
    audio_provider: str | None = typer.Option(
        None, help="Falls back to WorkflowState.audio_provider if omitted"
    ),
    topic_id: UUID | None = typer.Option(
        None, help="Optional: resolve missing IDs and record Flow credits/regenerations"
    ),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
    asset_root: Path | None = typer.Option(None, help="Override the configured asset root"),
) -> None:
    """Assemble a Storyboard's assets (+ optional audio) into a Production via FFmpeg."""
    try:
        store = _store(content_root)
        state = _load_or_create_workflow_state(store, topic_id) if topic_id is not None else None
        resolved_storyboard_id = _resolve_id(
            storyboard_id,
            state.storyboard_id if state else None,
            flag="--storyboard-id",
            label="storyboard_id",
        )
        resolved_manifest = _resolve_path(
            manifest,
            state.asset_manifest_path if state else None,
            flag="--manifest",
            label="manifest",
        )
        resolved_audio_path = (
            audio_path if audio_path is not None else (state.audio_path if state else None)
        )
        resolved_audio_source = (
            audio_source if audio_source is not None else (state.audio_source if state else None)
        )
        resolved_audio_provider = (
            audio_provider
            if audio_provider is not None
            else (state.audio_provider if state else None)
        )

        storyboard = store.load_storyboard(resolved_storyboard_id)
        resolved_asset_root = _asset_root(asset_root)
        asset_service = AssetService(resolved_asset_root)
        assembly_service = VideoAssemblyService(resolved_asset_root)

        assets = _import_assets_from_manifest(asset_service, storyboard, resolved_manifest)
        audio_track = _maybe_import_audio(
            assembly_service,
            storyboard,
            resolved_audio_path,
            resolved_audio_source,
            resolved_audio_provider,
        )

        production = assembly_service.assemble(storyboard, assets, audio_track)
        path = store.save_production(production)

        if state is not None:
            flow_credits_delta = sum(asset.flow_credits_used or 0 for asset in assets)
            _update_workflow_state(
                store,
                state,
                storyboard_id=resolved_storyboard_id,
                asset_manifest_path=str(resolved_manifest),
                audio_path=resolved_audio_path,
                audio_source=resolved_audio_source,
                audio_provider=resolved_audio_provider,
                production_id=production.id,
                assemble_regenerations=(
                    state.assemble_regenerations + (1 if state.production_id else 0)
                ),
                flow_credits_used=state.flow_credits_used + flow_credits_delta,
            )
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(f"production_id={production.id}")
    typer.echo(f"output_path={production.output_path}")
    typer.echo(f"captions_path={production.captions_path}")
    typer.echo(f"path={path}")


# --- review ---


@review_app.command("create")
def review_create(
    production_id: UUID | None = typer.Option(
        None, help="Falls back to WorkflowState.production_id if omitted (requires --topic-id)"
    ),
    topic_id: UUID | None = typer.Option(
        None, help="Optional: resolve missing --production-id and update WorkflowState"
    ),
    reviewer: str = typer.Option(...),
    checklist: Path = typer.Option(
        ..., help="JSON file mapping each of the ten ReviewCategory values to {passed, notes}"
    ),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
) -> None:
    """Create a PENDING Review for a Production. Never implies approval."""
    try:
        store = _store(content_root)
        state = _load_or_create_workflow_state(store, topic_id) if topic_id is not None else None
        resolved_production_id = _resolve_id(
            production_id,
            state.production_id if state else None,
            flag="--production-id",
            label="production_id",
        )

        production = store.load_production(resolved_production_id)
        parsed_checklist = _parse_checklist(checklist)
        review = ReviewService().create_review(production, reviewer, parsed_checklist)
        path = store.save_review(review)

        if state is not None:
            _update_workflow_state(
                store, state, production_id=resolved_production_id, review_id=review.id
            )
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(f"review_id={review.id}")
    typer.echo(f"status={review.status.value}")
    typer.echo(f"path={path}")


@review_app.command("approve")
def review_approve(
    review_id: UUID | None = typer.Option(
        None, help="Falls back to WorkflowState.review_id if omitted (requires --topic-id)"
    ),
    topic_id: UUID | None = typer.Option(
        None, help="Optional: resolve missing --review-id and update WorkflowState"
    ),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
) -> None:
    """Explicitly approve a PENDING Review. Terminal — cannot be changed afterward."""
    try:
        store = _store(content_root)
        state = _load_or_create_workflow_state(store, topic_id) if topic_id is not None else None
        resolved_review_id = _resolve_id(
            review_id, state.review_id if state else None, flag="--review-id", label="review_id"
        )

        review = store.load_review(resolved_review_id)
        approved = ReviewService().approve(review)
        path = store.save_review(approved)

        if state is not None:
            _update_workflow_state(store, state, review_id=resolved_review_id)
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(f"review_id={approved.id}")
    typer.echo(f"status={approved.status.value}")
    typer.echo(f"path={path}")


@review_app.command("reject")
def review_reject(
    review_id: UUID | None = typer.Option(
        None, help="Falls back to WorkflowState.review_id if omitted (requires --topic-id)"
    ),
    topic_id: UUID | None = typer.Option(
        None, help="Optional: resolve missing --review-id and update WorkflowState"
    ),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
) -> None:
    """Explicitly reject a PENDING Review. Terminal — cannot be changed afterward."""
    try:
        store = _store(content_root)
        state = _load_or_create_workflow_state(store, topic_id) if topic_id is not None else None
        resolved_review_id = _resolve_id(
            review_id, state.review_id if state else None, flag="--review-id", label="review_id"
        )

        review = store.load_review(resolved_review_id)
        rejected = ReviewService().reject(review)
        path = store.save_review(rejected)

        if state is not None:
            _update_workflow_state(store, state, review_id=resolved_review_id)
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(f"review_id={rejected.id}")
    typer.echo(f"status={rejected.status.value}")
    typer.echo(f"path={path}")


# --- package ---


@package_app.command("create")
def package_create(
    review_id: UUID | None = typer.Option(
        None, help="Falls back to WorkflowState.review_id if omitted (requires --topic-id)"
    ),
    production_id: UUID | None = typer.Option(
        None, help="Falls back to WorkflowState.production_id if omitted (requires --topic-id)"
    ),
    topic_id: UUID | None = typer.Option(
        None, help="Optional: resolve missing IDs and mark the workflow complete"
    ),
    title: str = typer.Option(...),
    source: list[str] = typer.Option([], help="Source reference (repeatable)"),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
) -> None:
    """Create a PublicationPackage from an APPROVED Review. The real approval gate.

    YouTube upload itself remains entirely manual and outside this CLI.
    """
    try:
        store = _store(content_root)
        state = _load_or_create_workflow_state(store, topic_id) if topic_id is not None else None
        resolved_review_id = _resolve_id(
            review_id, state.review_id if state else None, flag="--review-id", label="review_id"
        )
        resolved_production_id = _resolve_id(
            production_id,
            state.production_id if state else None,
            flag="--production-id",
            label="production_id",
        )

        review = store.load_review(resolved_review_id)
        production = store.load_production(resolved_production_id)
        package = ReviewService().create_publication_package(
            review, production, title, sources=list(source)
        )
        path = store.save_publication_package(package)

        if state is not None:
            _update_workflow_state(
                store,
                state,
                review_id=resolved_review_id,
                production_id=resolved_production_id,
                package_id=package.id,
                completed_at=utc_now(),
            )
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(f"package_id={package.id}")
    typer.echo(f"output_path={package.output_path}")
    typer.echo(f"captions_path={package.captions_path}")
    typer.echo(f"path={path}")


# --- budget ---


@budget_app.command("status")
def budget_status(
    budget_config: Path | None = typer.Option(
        None, help="Override the configured budget YAML path"
    ),
) -> None:
    """Show configured local budgets, current usage, and warning/hard-stop state.

    Never makes a provider call and never prints GEMINI_API_KEY or any
    other secret — only the budget configuration and locally tracked usage.
    """
    try:
        settings = get_settings()
        config_path = budget_config or Path(settings.budget_config)
        config = get_budget_settings(config_path)
        budgets = load_budgets_from_config(config)
        tracker = BudgetTracker(budgets)
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    if not budgets:
        typer.echo("No budgets configured.")
        return

    for name in sorted(budgets):
        budget = budgets[name]
        for unit_type in _dimensions_for(budget):
            result = tracker.check_allowance(name, units=0, unit_type=unit_type)
            typer.echo(
                f"{name}[{unit_type}] status={result.status.value} "
                f"usage={result.current_usage} local_budget={result.local_budget} "
                f"official_limit={result.official_limit} warning={result.warning_threshold} "
                f"hard_stop={result.hard_stop_threshold} reserve={result.reserve} "
                f"is_official_limit={result.is_official_limit}"
            )


# --- workflow ---


@workflow_app.command("show")
def workflow_show(
    topic_id: UUID = typer.Option(...),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
) -> None:
    """Print a Topic's WorkflowState — recovery/visibility tool, not a report.

    Useful when an ID was lost, or to confirm what a command will fall
    back to before running it without an explicit ``--*-id``.
    """
    try:
        store = _store(content_root)
        state = store.load_workflow_state(topic_id)
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(state.model_dump_json(indent=2))


# --- experiment ---


@experiment_app.command("record")
def experiment_record(
    topic_id: UUID = typer.Option(..., help="Topic this experiment record reports on"),
    metrics_file: Path | None = typer.Option(
        None, help="JSON file with any subset of the human-entered fields below"
    ),
    production_time_minutes: float | None = typer.Option(
        None, min=0, help="Human-estimated production time in minutes. Never auto-computed."
    ),
    incremental_ai_cost_notes: str | None = typer.Option(
        None, help="Free-text monetary cost note; leave unset on the free tier"
    ),
    publish_date: str | None = typer.Option(None, help="ISO date, e.g. 2026-09-20"),
    views: int | None = typer.Option(None, min=0),
    average_view_duration_seconds: float | None = typer.Option(None, min=0),
    percent_viewed: float | None = typer.Option(None, min=0, max=100),
    likes: int | None = typer.Option(None, min=0),
    comments: int | None = typer.Option(None, min=0),
    shares: int | None = typer.Option(None, min=0),
    subscribers_gained: int | None = typer.Option(None, help="May be negative"),
    quality_accuracy: int | None = typer.Option(None, min=1, max=5),
    quality_clarity: int | None = typer.Option(None, min=1, max=5),
    quality_hook: int | None = typer.Option(None, min=1, max=5),
    quality_visual_quality: int | None = typer.Option(None, min=1, max=5),
    quality_pacing: int | None = typer.Option(None, min=1, max=5),
    quality_originality: int | None = typer.Option(None, min=1, max=5),
    quality_overall: int | None = typer.Option(None, min=1, max=5),
    notes: str | None = typer.Option(None, help="Free-text lessons learned"),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
) -> None:
    """Create/update the ExperimentRecord for a Topic (PRD FR-12, §11).

    Production-side fields (regeneration count, Gemini usage, Flow credits,
    production/review/package IDs) are always pulled fresh from
    WorkflowState — there is no flag to override them. Everything else,
    including ``production_time_minutes``, is entered here by a human;
    nothing on this command is derived from any timestamp. Safe to re-run
    for the same topic: it upserts rather than duplicating.
    """
    try:
        store = _store(content_root)
        topic = store.load_topic(topic_id)
        state = _load_or_create_workflow_state(store, topic_id)

        try:
            existing = store.load_experiment_record(topic_id)
        except ArtifactNotFoundError:
            existing = ExperimentRecord(
                topic_id=topic_id, title=topic.title, category=topic.category
            )

        file_overrides: dict[str, Any] = {}
        if metrics_file is not None:
            raw = _read_json_file(metrics_file)
            if not isinstance(raw, dict):
                raise CLIError(f"Metrics file must contain a JSON object: {metrics_file}")
            file_overrides = dict(raw)
        file_quality = dict(file_overrides.pop("quality", {}) or {})
        # Metrics files are partial updates: an explicit null for a field means
        # "not supplied here," not "clear this field" — otherwise a metrics
        # file that only intends to add one field would silently wipe every
        # other field it happens to list as null (e.g. a hand-edited template).
        # Mirrors the None-filtering already applied to flag_overrides below.
        file_overrides = {k: v for k, v in file_overrides.items() if v is not None}
        file_quality = {k: v for k, v in file_quality.items() if v is not None}

        flag_overrides = {
            "production_time_minutes": production_time_minutes,
            "incremental_ai_cost_notes": incremental_ai_cost_notes,
            "publish_date": publish_date,
            "views": views,
            "average_view_duration_seconds": average_view_duration_seconds,
            "percent_viewed": percent_viewed,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "subscribers_gained": subscribers_gained,
            "notes": notes,
        }
        flag_overrides = {k: v for k, v in flag_overrides.items() if v is not None}

        quality_flag_overrides = {
            "accuracy": quality_accuracy,
            "clarity": quality_clarity,
            "hook": quality_hook,
            "visual_quality": quality_visual_quality,
            "pacing": quality_pacing,
            "originality": quality_originality,
            "overall": quality_overall,
        }
        quality_flag_overrides = {k: v for k, v in quality_flag_overrides.items() if v is not None}

        data = existing.model_dump()
        data.update(file_overrides)
        data.update(flag_overrides)
        data["quality"] = {**data["quality"], **file_quality, **quality_flag_overrides}

        # Always refreshed from the source of truth — no flag can override these.
        data["title"] = topic.title
        data["category"] = topic.category
        data["production_id"] = state.production_id
        data["review_id"] = state.review_id
        data["package_id"] = state.package_id
        data["regeneration_count"] = (
            state.brief_regenerations
            + state.script_regenerations
            + state.storyboard_regenerations
            + state.assemble_regenerations
        )
        data["gemini_requests_used"] = state.gemini_requests_used
        data["gemini_tokens_used"] = state.gemini_tokens_used
        data["flow_credits_used"] = state.flow_credits_used
        data["updated_at"] = utc_now()

        try:
            record = ExperimentRecord.model_validate(data)
        except ValidationError as exc:
            raise CLIError(f"Invalid experiment metrics: {exc}") from exc

        path = store.save_experiment_record(record)
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(f"topic_id={record.topic_id}")
    typer.echo(f"regeneration_count={record.regeneration_count}")
    typer.echo(f"path={path}")


@experiment_app.command("list")
def experiment_list(
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
) -> None:
    """Print one summary line per persisted ExperimentRecord."""
    try:
        store = _store(content_root)
        records = store.list_experiment_records()
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    if not records:
        typer.echo("No experiment records found.")
        return

    for record in sorted(records, key=lambda r: r.title.lower()):
        views = record.views if record.views is not None else "-"
        typer.echo(
            f"{record.topic_id} | {record.title} | {record.category.value} | "
            f"regenerations={record.regeneration_count} | "
            f"gemini_requests={record.gemini_requests_used} | "
            f"flow_credits={record.flow_credits_used} | "
            f"views={views}"
        )


_EXPERIMENT_CSV_FIELDS = (
    "topic_id",
    "title",
    "category",
    "production_id",
    "review_id",
    "package_id",
    "production_time_minutes",
    "regeneration_count",
    "gemini_requests_used",
    "gemini_tokens_used",
    "flow_credits_used",
    "incremental_ai_cost_notes",
    "publish_date",
    "views",
    "average_view_duration_seconds",
    "percent_viewed",
    "likes",
    "comments",
    "shares",
    "subscribers_gained",
    "quality_accuracy",
    "quality_clarity",
    "quality_hook",
    "quality_visual_quality",
    "quality_pacing",
    "quality_originality",
    "quality_overall",
    "notes",
)


def _experiment_csv_row(record: ExperimentRecord) -> dict[str, Any]:
    return {
        "topic_id": record.topic_id,
        "title": record.title,
        "category": record.category.value,
        "production_id": record.production_id,
        "review_id": record.review_id,
        "package_id": record.package_id,
        "production_time_minutes": record.production_time_minutes,
        "regeneration_count": record.regeneration_count,
        "gemini_requests_used": record.gemini_requests_used,
        "gemini_tokens_used": record.gemini_tokens_used,
        "flow_credits_used": record.flow_credits_used,
        "incremental_ai_cost_notes": record.incremental_ai_cost_notes,
        "publish_date": record.publish_date,
        "views": record.views,
        "average_view_duration_seconds": record.average_view_duration_seconds,
        "percent_viewed": record.percent_viewed,
        "likes": record.likes,
        "comments": record.comments,
        "shares": record.shares,
        "subscribers_gained": record.subscribers_gained,
        "quality_accuracy": record.quality.accuracy,
        "quality_clarity": record.quality.clarity,
        "quality_hook": record.quality.hook,
        "quality_visual_quality": record.quality.visual_quality,
        "quality_pacing": record.quality.pacing,
        "quality_originality": record.quality.originality,
        "quality_overall": record.quality.overall,
        "notes": record.notes,
    }


@experiment_app.command("export-csv")
def experiment_export_csv(
    output: Path = typer.Option(..., help="CSV file to write"),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
) -> None:
    """Export all ExperimentRecords to a flat CSV for spreadsheet review.

    Derived output only, regenerable at any time from the persisted JSON
    records — CSV is never the source of truth and is never read back in.
    """
    try:
        store = _store(content_root)
        records = store.list_experiment_records()

        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(_EXPERIMENT_CSV_FIELDS))
            writer.writeheader()
            for record in sorted(records, key=lambda r: r.title.lower()):
                writer.writerow(_experiment_csv_row(record))
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(f"records_exported={len(records)}")
    typer.echo(f"path={output}")


if __name__ == "__main__":
    app()
