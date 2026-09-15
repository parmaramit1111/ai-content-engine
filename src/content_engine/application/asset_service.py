"""Visual asset preparation service — validates human-imported Flow clips.

Implements the Phase 09 asset vertical slice:

    Storyboard + (scene_number, path, source, ...)
        → AssetService.import_asset()
        → filesystem + metadata validation (no provider call)
        → validated Asset

Google Flow (and any other visual-generation tool) is entirely
human-in-the-loop: this service never calls an external provider, never
queries Flow account/API state, and never generates, copies, moves, or
otherwise writes media. It only validates that a file the human already
placed on disk is real, is inside the configured asset root, and has a
plausible video extension — then records the human-supplied metadata as-is.

Flow credit usage (``flow_credits_used``) is recorded as plain metadata
only. This service never calls ``BudgetTracker.record_usage`` — that
remains a deliberately separate, not-yet-wired concern.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from content_engine.domain.models import Asset, Storyboard

_ALLOWED_EXTENSIONS = frozenset({".mp4", ".mov", ".webm"})


class AssetServiceError(Exception):
    """Raised when asset import validation fails."""


class AssetService:
    """Validate and construct Asset records for human-imported visual clips.

    No provider dependency, no budget-tracker dependency, no filesystem
    writes — the service only reads/checks the filesystem to confirm an
    already-existing file is real and within bounds.

    Args:
        asset_root: The configured local asset root (``AppSettings.asset_root``).
            All imported asset paths must resolve inside this directory.
    """

    def __init__(self, asset_root: Path):
        self._asset_root = asset_root.resolve()

    def import_asset(
        self,
        storyboard: Storyboard,
        scene_number: int,
        path: str,
        *,
        source: str,
        provider: str | None = None,
        flow_credits_used: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Asset:
        """Validate a human-imported clip and return a validated Asset.

        Args:
            storyboard: The Storyboard this clip belongs to.
            scene_number: Which storyboard scene this clip is for.
            path: Filesystem path to the clip, relative or absolute.
            source: High-level provenance (e.g. "google_flow", "manual").
            provider: Specific generation provider/model, if known.
            flow_credits_used: Human-reported Flow credits spent, if any.
            metadata: Additional human-supplied metadata.

        Returns:
            A validated Asset. The storyboard and the source file are
            never modified.

        Raises:
            AssetServiceError: If any validation step fails.
        """
        self._validate_scene_number(storyboard, scene_number)
        resolved_path = self._validate_path(path)
        self._validate_extension(resolved_path)
        validated_source = self._validate_non_empty(source, "source")
        validated_provider = self._validate_optional_non_empty(provider, "provider")
        validated_credits = self._validate_flow_credits(flow_credits_used)

        return Asset(
            storyboard_id=storyboard.id,
            scene_number=scene_number,
            path=str(resolved_path),
            source=validated_source,
            provider=validated_provider,
            flow_credits_used=validated_credits,
            metadata=metadata,
        )

    def all_scenes_covered(self, storyboard: Storyboard, assets: list[Asset]) -> bool:
        """Return True only if every scene in the storyboard has at least one asset.

        Matching is by (storyboard_id, scene_number); assets belonging to a
        different storyboard never count toward this storyboard's coverage.
        Multiple assets for the same scene are fine — this only checks
        presence, never selects a preferred asset.
        """
        covered_scene_numbers = {
            asset.scene_number for asset in assets if asset.storyboard_id == storyboard.id
        }
        expected_scene_numbers = {scene.number for scene in storyboard.scenes}
        return expected_scene_numbers.issubset(covered_scene_numbers)

    @staticmethod
    def _validate_scene_number(storyboard: Storyboard, scene_number: int) -> None:
        if isinstance(scene_number, bool) or not isinstance(scene_number, int):
            raise AssetServiceError(
                f"scene_number must be an integer, got {type(scene_number).__name__}"
            )
        valid_numbers = {scene.number for scene in storyboard.scenes}
        if scene_number not in valid_numbers:
            raise AssetServiceError(
                f"Scene {scene_number} does not exist in storyboard {storyboard.id} "
                f"(valid scene numbers: {sorted(valid_numbers)})"
            )

    def _validate_path(self, path: str) -> Path:
        if path is None or not isinstance(path, str) or not path.strip():
            raise AssetServiceError("path is missing or empty")

        candidate = Path(path.strip())
        if not candidate.is_absolute():
            candidate = self._asset_root / candidate
        resolved = candidate.resolve()

        try:
            resolved.relative_to(self._asset_root)
        except ValueError as exc:
            raise AssetServiceError(
                f"Asset path {resolved} resolves outside the configured asset root "
                f"{self._asset_root}"
            ) from exc

        if not resolved.exists():
            raise AssetServiceError(f"Asset file does not exist: {resolved}")
        if not resolved.is_file():
            raise AssetServiceError(f"Asset path is not a regular file: {resolved}")

        return resolved

    @staticmethod
    def _validate_extension(resolved_path: Path) -> None:
        extension = resolved_path.suffix.lower()
        if extension not in _ALLOWED_EXTENSIONS:
            allowed = sorted(_ALLOWED_EXTENSIONS)
            raise AssetServiceError(
                f"Unsupported video extension '{resolved_path.suffix}' for {resolved_path}; "
                f"must be one of {allowed}"
            )

    @staticmethod
    def _validate_non_empty(value: Any, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise AssetServiceError(f"{field_name} is missing or empty")
        return value.strip()

    @staticmethod
    def _validate_optional_non_empty(value: str | None, field_name: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise AssetServiceError(f"{field_name} must not be empty when supplied")
        return value.strip()

    @staticmethod
    def _validate_flow_credits(value: int | None) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            raise AssetServiceError(
                f"flow_credits_used must be an integer, got {type(value).__name__}"
            )
        if isinstance(value, float) and not value.is_integer():
            raise AssetServiceError(f"flow_credits_used must be a whole number, got {value}")
        if not isinstance(value, int | float):
            raise AssetServiceError(
                f"flow_credits_used must be an integer, got {type(value).__name__}"
            )
        credits = int(value)
        if credits < 1:
            raise AssetServiceError(f"flow_credits_used must be > 0, got {credits}")
        return credits
