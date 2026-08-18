from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import apps.import_infinigen_scene as importer
from apps.import_infinigen_scene import (
    _is_room_exterior_prototype,
    _is_tiny_highpoly_decoration,
)


def test_room_exterior_asset_prototypes_are_filtered_by_collection() -> None:
    assert _is_room_exterior_prototype({
        "id": "bedroom_0_0.exterior",
        "collections": ["unique_assets:room_exterior"],
    })
    assert not _is_room_exterior_prototype({
        "id": "placed_room.exterior",
        "collections": ["scene:architecture"],
    })
    assert not _is_room_exterior_prototype({
        "id": "ordinary_wall",
        "collections": [],
    })


def test_tiny_highpoly_filter_is_narrow_and_semantic() -> None:
    candidate = {
        "factory": "NatureShelfTrinketsFactory",
        "semantic_type": "shelf",
        "dimensions": [0.10, 0.12, 0.08],
        "triangles": 500_000,
    }
    assert _is_tiny_highpoly_decoration(candidate)
    assert not _is_tiny_highpoly_decoration({**candidate, "triangles": 249_999})
    assert not _is_tiny_highpoly_decoration({**candidate, "dimensions": [0.10, 0.151, 0.08]})
    assert not _is_tiny_highpoly_decoration({**candidate, "factory": "JarFactory"})
    assert not _is_tiny_highpoly_decoration({**candidate, "semantic_type": "landmark"})


def test_repo_relative_import_root_keeps_internal_path(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    manifest_dir = repo / "out" / "infinigen_imports" / "scene"
    manifest_dir.mkdir(parents=True)
    monkeypatch.setattr(importer, "REPO_ROOT", repo)

    assert importer._repo_relative_import_root(manifest_dir, "scene") == "out/infinigen_imports/scene"


def test_repo_relative_import_root_aliases_external_path(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    external = tmp_path / "bean" / "pipeline" / "stage1"
    repo.mkdir()
    external.mkdir(parents=True)
    (external / "mesh.glb").write_bytes(b"glb")
    monkeypatch.setattr(importer, "REPO_ROOT", repo)

    ref = importer._repo_relative_import_root(external, "derived/scene")
    alias = repo / ref
    assert alias.is_symlink()
    assert alias.resolve() == external.resolve()
    assert (repo / ref / "mesh.glb").read_bytes() == b"glb"
    assert importer._repo_relative_import_root(external, "derived/scene") == ref


def test_display_path_accepts_repo_external_snapshot(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    internal = repo / "out" / "snapshot"
    external = tmp_path / "bean" / "snapshot"
    monkeypatch.setattr(importer, "REPO_ROOT", repo)

    assert importer._display_path(internal) == "out/snapshot"
    assert importer._display_path(external) == str(external)
