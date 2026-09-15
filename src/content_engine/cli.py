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
"""

from __future__ import annotations

import asyncio
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
from content_engine.domain.models import (
    Asset,
    AudioTrack,
    ChecklistItem,
    Storyboard,
    Topic,
    utc_now,
)
from content_engine.providers.exceptions import (
    ProviderAPIError,
    ProviderConfigurationError,
    ProviderQuotaError,
)
from content_engine.providers.gemini.provider import GeminiProvider
from content_engine.storage import ContentStore, StorageError


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


def _build_gemini_provider(settings: AppSettings) -> GeminiProvider:
    """Wire a GeminiProvider from configured settings + the budget YAML.

    Never bypasses budget enforcement: the returned provider always checks
    ``BudgetTracker`` before every call (ARCHITECTURE §5, §7).
    """
    if not settings.gemini_model:
        raise CLIError("GEMINI_MODEL is not configured; set it via environment or .env")

    budget_config = get_budget_settings(settings.budget_config)
    budgets = load_budgets_from_config(budget_config)
    tracker = BudgetTracker(budgets)
    return GeminiProvider(
        api_key=settings.gemini_api_key, model=settings.gemini_model, tracker=tracker
    )


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
    """Create a Topic and persist it via ContentStore."""
    try:
        topic = Topic(
            title=title,
            category=category,
            audience=audience,
            difficulty=difficulty,
            hook=hook,
            source_refs=list(source_ref),
        )
        path = _store(content_root).save_topic(topic)
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
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(f"research_id={research.id}")
    typer.echo(f"verification_status={research.verification_status.value}")
    typer.echo(f"path={path}")


@research_app.command("verify")
def research_verify(
    research_id: UUID = typer.Option(...),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
) -> None:
    """Record that a human has verified previously-recorded research."""
    try:
        store = _store(content_root)
        research = store.load_research_notes(research_id)
        verified = research.model_copy(
            update={
                "verification_status": ResearchVerificationStatus.VERIFIED,
                "updated_at": utc_now(),
            }
        )
        path = store.save_research_notes(verified)
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
    topic_id: UUID = typer.Option(...),
    research_id: UUID = typer.Option(...),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
) -> None:
    """Generate a ContentBrief from a Topic + verified ResearchNotes via Gemini."""
    try:
        store = _store(content_root)
        topic = store.load_topic(topic_id)
        research = store.load_research_notes(research_id)
        if not ResearchService().is_ready_for_brief(research):
            raise CLIError(
                f"Research {research.id} is not ready for brief generation: "
                "must be VERIFIED with at least one key fact and one primary source"
            )
        provider = _build_gemini_provider(get_settings())
        brief = asyncio.run(BriefService(provider).generate_brief(topic, research))
        path = store.save_content_brief(brief)
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(f"brief_id={brief.id}")
    typer.echo(f"path={path}")


# --- script ---


@script_app.command("generate")
def script_generate(
    brief_id: UUID = typer.Option(...),
    version: int = typer.Option(1, min=1),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
) -> None:
    """Generate a Script from a ContentBrief via Gemini."""
    try:
        store = _store(content_root)
        brief = store.load_content_brief(brief_id)
        provider = _build_gemini_provider(get_settings())
        script = asyncio.run(ScriptService(provider).generate_script(brief, version=version))
        path = store.save_script(script)
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(f"script_id={script.id}")
    typer.echo(f"path={path}")


# --- storyboard ---


@storyboard_app.command("generate")
def storyboard_generate(
    script_id: UUID = typer.Option(...),
    brief_id: UUID = typer.Option(...),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
) -> None:
    """Generate a Storyboard (enriched visual prompts) from a Script + ContentBrief via Gemini."""
    try:
        store = _store(content_root)
        script = store.load_script(script_id)
        brief = store.load_content_brief(brief_id)
        provider = _build_gemini_provider(get_settings())
        storyboard = asyncio.run(StoryboardService(provider).generate_storyboard(script, brief))
        path = store.save_storyboard(storyboard)
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
    storyboard_id: UUID = typer.Option(...),
    manifest: Path = typer.Option(..., help="JSON array of {scene_number, path, source, ...}"),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
    asset_root: Path | None = typer.Option(None, help="Override the configured asset root"),
) -> None:
    """Validate an entire manifest of clips against a Storyboard's scene coverage."""
    try:
        store = _store(content_root)
        storyboard = store.load_storyboard(storyboard_id)
        service = AssetService(_asset_root(asset_root))
        assets = _import_assets_from_manifest(service, storyboard, manifest)
        covered = service.all_scenes_covered(storyboard, assets)
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
    storyboard_id: UUID = typer.Option(...),
    manifest: Path = typer.Option(..., help="JSON array of {scene_number, path, source, ...}"),
    audio_path: str | None = typer.Option(None, help="Path to narration/audio, if any"),
    audio_source: str | None = typer.Option(None, help="Required when --audio-path is given"),
    audio_provider: str | None = typer.Option(None),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
    asset_root: Path | None = typer.Option(None, help="Override the configured asset root"),
) -> None:
    """Assemble a Storyboard's assets (+ optional audio) into a Production via FFmpeg."""
    try:
        store = _store(content_root)
        storyboard = store.load_storyboard(storyboard_id)
        resolved_asset_root = _asset_root(asset_root)
        asset_service = AssetService(resolved_asset_root)
        assembly_service = VideoAssemblyService(resolved_asset_root)

        assets = _import_assets_from_manifest(asset_service, storyboard, manifest)
        audio_track = _maybe_import_audio(
            assembly_service, storyboard, audio_path, audio_source, audio_provider
        )

        production = assembly_service.assemble(storyboard, assets, audio_track)
        path = store.save_production(production)
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(f"production_id={production.id}")
    typer.echo(f"output_path={production.output_path}")
    typer.echo(f"captions_path={production.captions_path}")
    typer.echo(f"path={path}")


# --- review ---


@review_app.command("create")
def review_create(
    production_id: UUID = typer.Option(...),
    reviewer: str = typer.Option(...),
    checklist: Path = typer.Option(
        ..., help="JSON file mapping each of the ten ReviewCategory values to {passed, notes}"
    ),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
) -> None:
    """Create a PENDING Review for a Production. Never implies approval."""
    try:
        store = _store(content_root)
        production = store.load_production(production_id)
        parsed_checklist = _parse_checklist(checklist)
        review = ReviewService().create_review(production, reviewer, parsed_checklist)
        path = store.save_review(review)
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(f"review_id={review.id}")
    typer.echo(f"status={review.status.value}")
    typer.echo(f"path={path}")


@review_app.command("approve")
def review_approve(
    review_id: UUID = typer.Option(...),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
) -> None:
    """Explicitly approve a PENDING Review. Terminal — cannot be changed afterward."""
    try:
        store = _store(content_root)
        review = store.load_review(review_id)
        approved = ReviewService().approve(review)
        path = store.save_review(approved)
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(f"review_id={approved.id}")
    typer.echo(f"status={approved.status.value}")
    typer.echo(f"path={path}")


@review_app.command("reject")
def review_reject(
    review_id: UUID = typer.Option(...),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
) -> None:
    """Explicitly reject a PENDING Review. Terminal — cannot be changed afterward."""
    try:
        store = _store(content_root)
        review = store.load_review(review_id)
        rejected = ReviewService().reject(review)
        path = store.save_review(rejected)
    except _KNOWN_ERRORS as exc:
        _fail(str(exc))

    typer.echo(f"review_id={rejected.id}")
    typer.echo(f"status={rejected.status.value}")
    typer.echo(f"path={path}")


# --- package ---


@package_app.command("create")
def package_create(
    review_id: UUID = typer.Option(...),
    production_id: UUID = typer.Option(...),
    title: str = typer.Option(...),
    source: list[str] = typer.Option([], help="Source reference (repeatable)"),
    content_root: Path | None = typer.Option(None, help="Override the configured content root"),
) -> None:
    """Create a PublicationPackage from an APPROVED Review. The real approval gate.

    YouTube upload itself remains entirely manual and outside this CLI.
    """
    try:
        store = _store(content_root)
        review = store.load_review(review_id)
        production = store.load_production(production_id)
        package = ReviewService().create_publication_package(
            review, production, title, sources=list(source)
        )
        path = store.save_publication_package(package)
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


if __name__ == "__main__":
    app()
