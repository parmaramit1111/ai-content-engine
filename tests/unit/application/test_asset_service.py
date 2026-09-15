"""Focused unit tests for the AssetService vertical slice.

Tests cover:
1.  happy paths: valid import, relative/absolute paths inside asset_root,
    optional provider/flow_credits/metadata, multiple assets per scene,
    all_scenes_covered()
2.  scene validation: unknown scene number, boolean scene number, assets
    from a different storyboard not counted toward coverage
3.  path validation: missing/empty path, missing file, directory path,
    path outside asset_root, path traversal, unsupported/missing
    extension, case-insensitive extension matching
4.  metadata validation: missing/empty source, empty provider when
    supplied, negative/zero/boolean/fractional flow credits
5.  side-effect boundaries: storyboard untouched, source file untouched,
    no budget-tracker or provider coupling (via module import inspection)

No filesystem writes by the service itself. Uses pytest's tmp_path for
ephemeral fixture files — no binary media is committed to the repository.
"""

import ast
from inspect import getsource
from pathlib import Path
from uuid import uuid4

import pytest

from content_engine.application import asset_service as asset_service_module
from content_engine.application.asset_service import AssetService, AssetServiceError
from content_engine.domain.models import Asset, Scene, Storyboard


def _make_scene(**overrides) -> Scene:
    defaults = {
        "number": 1,
        "duration": 5.0,
        "narration": "Hook narration",
        "visual_prompt": "Wide shot of a robot thinking",
    }
    defaults.update(overrides)
    return Scene(**defaults)


def _make_storyboard(scenes: list[Scene] | None = None, **overrides) -> Storyboard:
    if scenes is None:
        scenes = [_make_scene(number=1), _make_scene(number=2)]
    defaults = {"script_id": uuid4(), "scenes": scenes}
    defaults.update(overrides)
    return Storyboard(**defaults)


def _make_clip(tmp_path: Path, name: str = "clip.mp4", content: bytes = b"fake video data") -> Path:
    clip = tmp_path / name
    clip.write_bytes(content)
    return clip


class TestAssetServiceHappyPaths:
    def test_valid_asset_import(self, tmp_path: Path):
        clip = _make_clip(tmp_path)
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        asset = service.import_asset(
            storyboard, scene_number=1, path=str(clip), source="google_flow"
        )

        assert isinstance(asset, Asset)
        assert asset.storyboard_id == storyboard.id
        assert asset.scene_number == 1
        assert asset.source == "google_flow"
        assert Path(asset.path) == clip.resolve()

    def test_relative_path_inside_asset_root(self, tmp_path: Path):
        _make_clip(tmp_path, name="clip.mp4")
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        asset = service.import_asset(
            storyboard, scene_number=1, path="clip.mp4", source="google_flow"
        )

        assert Path(asset.path) == (tmp_path / "clip.mp4").resolve()

    def test_absolute_path_inside_asset_root(self, tmp_path: Path):
        clip = _make_clip(tmp_path)
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        asset = service.import_asset(
            storyboard, scene_number=1, path=str(clip.resolve()), source="google_flow"
        )

        assert Path(asset.path) == clip.resolve()

    def test_optional_provider(self, tmp_path: Path):
        clip = _make_clip(tmp_path)
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        asset = service.import_asset(
            storyboard,
            scene_number=1,
            path=str(clip),
            source="google_flow",
            provider="veo-3.1-fast",
        )

        assert asset.provider == "veo-3.1-fast"

    def test_optional_flow_credits(self, tmp_path: Path):
        clip = _make_clip(tmp_path)
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        asset = service.import_asset(
            storyboard,
            scene_number=1,
            path=str(clip),
            source="google_flow",
            flow_credits_used=20,
        )

        assert asset.flow_credits_used == 20

    def test_optional_metadata(self, tmp_path: Path):
        clip = _make_clip(tmp_path)
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        asset = service.import_asset(
            storyboard,
            scene_number=1,
            path=str(clip),
            source="google_flow",
            metadata={"attempt": 1},
        )

        assert asset.metadata == {"attempt": 1}

    def test_multiple_assets_for_same_scene_allowed(self, tmp_path: Path):
        clip1 = _make_clip(tmp_path, name="attempt-01.mp4")
        clip2 = _make_clip(tmp_path, name="attempt-02.mp4")
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        asset1 = service.import_asset(
            storyboard, scene_number=1, path=str(clip1), source="google_flow"
        )
        asset2 = service.import_asset(
            storyboard, scene_number=1, path=str(clip2), source="google_flow"
        )

        assert asset1.id != asset2.id
        assert asset1.scene_number == asset2.scene_number == 1

    def test_all_scenes_covered_true_when_every_scene_has_an_asset(self, tmp_path: Path):
        clip1 = _make_clip(tmp_path, name="scene1.mp4")
        clip2 = _make_clip(tmp_path, name="scene2.mp4")
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        asset1 = service.import_asset(
            storyboard, scene_number=1, path=str(clip1), source="google_flow"
        )
        asset2 = service.import_asset(
            storyboard, scene_number=2, path=str(clip2), source="google_flow"
        )

        assert service.all_scenes_covered(storyboard, [asset1, asset2]) is True

    def test_all_scenes_covered_false_when_a_scene_is_missing(self, tmp_path: Path):
        clip1 = _make_clip(tmp_path, name="scene1.mp4")
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        asset1 = service.import_asset(
            storyboard, scene_number=1, path=str(clip1), source="google_flow"
        )

        assert service.all_scenes_covered(storyboard, [asset1]) is False


class TestAssetServiceSceneValidation:
    def test_unknown_scene_number_rejected(self, tmp_path: Path):
        clip = _make_clip(tmp_path)
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        with pytest.raises(AssetServiceError, match="does not exist in storyboard"):
            service.import_asset(storyboard, scene_number=99, path=str(clip), source="google_flow")

    def test_boolean_scene_number_rejected(self, tmp_path: Path):
        clip = _make_clip(tmp_path)
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        with pytest.raises(AssetServiceError, match="scene_number must be an integer"):
            service.import_asset(
                storyboard, scene_number=True, path=str(clip), source="google_flow"
            )

    def test_asset_from_different_storyboard_not_counted_as_coverage(self, tmp_path: Path):
        clip = _make_clip(tmp_path)
        storyboard_a = _make_storyboard()
        storyboard_b = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        asset_for_b = service.import_asset(
            storyboard_b, scene_number=1, path=str(clip), source="google_flow"
        )

        assert service.all_scenes_covered(storyboard_a, [asset_for_b]) is False


class TestAssetServicePathValidation:
    def test_missing_path_rejected(self, tmp_path: Path):
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        with pytest.raises(AssetServiceError, match="path is missing or empty"):
            service.import_asset(storyboard, scene_number=1, path=None, source="google_flow")

    def test_empty_path_rejected(self, tmp_path: Path):
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        with pytest.raises(AssetServiceError, match="path is missing or empty"):
            service.import_asset(storyboard, scene_number=1, path="   ", source="google_flow")

    def test_missing_file_rejected(self, tmp_path: Path):
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        with pytest.raises(AssetServiceError, match="does not exist"):
            service.import_asset(
                storyboard, scene_number=1, path="does-not-exist.mp4", source="google_flow"
            )

    def test_directory_path_rejected(self, tmp_path: Path):
        subdir = tmp_path / "a_directory.mp4"
        subdir.mkdir()
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        with pytest.raises(AssetServiceError, match="not a regular file"):
            service.import_asset(
                storyboard, scene_number=1, path=str(subdir), source="google_flow"
            )

    def test_path_outside_asset_root_rejected(self, tmp_path: Path):
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside.mp4"
        outside.write_bytes(b"data")
        storyboard = _make_storyboard()
        service = AssetService(asset_root=root)

        with pytest.raises(AssetServiceError, match="outside the configured asset root"):
            service.import_asset(
                storyboard, scene_number=1, path=str(outside), source="google_flow"
            )

    def test_path_traversal_rejected(self, tmp_path: Path):
        root = tmp_path / "root"
        root.mkdir()
        secret = tmp_path / "secret.mp4"
        secret.write_bytes(b"data")
        storyboard = _make_storyboard()
        service = AssetService(asset_root=root)

        with pytest.raises(AssetServiceError, match="outside the configured asset root"):
            service.import_asset(
                storyboard, scene_number=1, path="../secret.mp4", source="google_flow"
            )

    def test_unsupported_extension_rejected(self, tmp_path: Path):
        clip = _make_clip(tmp_path, name="clip.avi")
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        with pytest.raises(AssetServiceError, match="Unsupported video extension"):
            service.import_asset(storyboard, scene_number=1, path=str(clip), source="google_flow")

    def test_missing_extension_rejected(self, tmp_path: Path):
        clip = _make_clip(tmp_path, name="clip")
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        with pytest.raises(AssetServiceError, match="Unsupported video extension"):
            service.import_asset(storyboard, scene_number=1, path=str(clip), source="google_flow")

    def test_extension_matching_is_case_insensitive(self, tmp_path: Path):
        clip = _make_clip(tmp_path, name="clip.MP4")
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        asset = service.import_asset(
            storyboard, scene_number=1, path=str(clip), source="google_flow"
        )

        assert asset.path.endswith("clip.MP4")


class TestAssetServiceMetadataValidation:
    def test_missing_source_rejected(self, tmp_path: Path):
        clip = _make_clip(tmp_path)
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        with pytest.raises(AssetServiceError, match="source is missing or empty"):
            service.import_asset(storyboard, scene_number=1, path=str(clip), source=None)

    def test_empty_source_rejected(self, tmp_path: Path):
        clip = _make_clip(tmp_path)
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        with pytest.raises(AssetServiceError, match="source is missing or empty"):
            service.import_asset(storyboard, scene_number=1, path=str(clip), source="   ")

    def test_empty_provider_rejected_when_supplied(self, tmp_path: Path):
        clip = _make_clip(tmp_path)
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        with pytest.raises(AssetServiceError, match="provider must not be empty"):
            service.import_asset(
                storyboard, scene_number=1, path=str(clip), source="google_flow", provider="   "
            )

    def test_negative_flow_credits_rejected(self, tmp_path: Path):
        clip = _make_clip(tmp_path)
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        with pytest.raises(AssetServiceError, match="flow_credits_used must be > 0"):
            service.import_asset(
                storyboard,
                scene_number=1,
                path=str(clip),
                source="google_flow",
                flow_credits_used=-5,
            )

    def test_zero_flow_credits_rejected(self, tmp_path: Path):
        clip = _make_clip(tmp_path)
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        with pytest.raises(AssetServiceError, match="flow_credits_used must be > 0"):
            service.import_asset(
                storyboard,
                scene_number=1,
                path=str(clip),
                source="google_flow",
                flow_credits_used=0,
            )

    def test_boolean_flow_credits_rejected(self, tmp_path: Path):
        clip = _make_clip(tmp_path)
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        with pytest.raises(AssetServiceError, match="flow_credits_used must be an integer"):
            service.import_asset(
                storyboard,
                scene_number=1,
                path=str(clip),
                source="google_flow",
                flow_credits_used=True,
            )

    def test_fractional_flow_credits_rejected(self, tmp_path: Path):
        clip = _make_clip(tmp_path)
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        with pytest.raises(AssetServiceError, match="flow_credits_used must be a whole number"):
            service.import_asset(
                storyboard,
                scene_number=1,
                path=str(clip),
                source="google_flow",
                flow_credits_used=20.5,
            )


class TestAssetServiceSideEffectBoundaries:
    def test_importing_asset_does_not_modify_storyboard(self, tmp_path: Path):
        clip = _make_clip(tmp_path)
        storyboard = _make_storyboard()
        before = storyboard.model_copy(deep=True)
        service = AssetService(asset_root=tmp_path)

        service.import_asset(storyboard, scene_number=1, path=str(clip), source="google_flow")

        assert storyboard == before

    def test_importing_asset_does_not_modify_source_file(self, tmp_path: Path):
        clip = _make_clip(tmp_path, content=b"original content")
        storyboard = _make_storyboard()
        service = AssetService(asset_root=tmp_path)

        service.import_asset(storyboard, scene_number=1, path=str(clip), source="google_flow")

        assert clip.read_bytes() == b"original content"

    def test_service_has_no_budget_or_provider_coupling(self):
        """No import anywhere in the asset_service module may reference the
        budget tracker or any external/AI provider (Gemini, Flow API, HTTP)."""
        tree = ast.parse(getsource(asset_service_module))
        imported_names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imported_names.append(module)
                imported_names.extend(f"{module}.{alias.name}" for alias in node.names)

        joined = " ".join(imported_names).lower()
        assert "budget" not in joined
        assert "gemini" not in joined
        assert "google" not in joined
        assert "requests" not in joined
        assert "httpx" not in joined


class TestAssetServiceInvalidRootConstruction:
    def test_asset_root_resolved_at_construction(self, tmp_path: Path):
        """The asset root itself is resolved once at construction time."""
        service = AssetService(asset_root=tmp_path)
        assert service._asset_root == tmp_path.resolve()
