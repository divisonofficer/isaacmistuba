from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from navigation_dataset.cli import cmd_graph_build
from navigation_dataset.episode_schema import EpisodeManifest, EpisodeTimestep, write_episode
from navigation_dataset.exporters.custom_json import find_episode_files
from navigation_dataset.scene_dataset import (
    PROJECT_CATALOG_VERSION,
    SceneDatasetPaths,
    page_episode_index,
    write_episode_index,
    write_project_catalog,
    write_scene_dataset,
)
from navigation_dataset.scene_workspace_migration import migrate_scene_layout
from navigation_dataset.validation import validate_dataset


def _episode(scene_id: str, episode_id: str) -> EpisodeManifest:
    return EpisodeManifest(
        episode_id=episode_id,
        scene_id=scene_id,
        split="train",
        start_pose=[0.0, 0.0, 0.0],
        goal_pose=[1.0, 0.0, 0.0],
        goal_region="goal",
        natural_language_instruction="go",
        trajectory=[[0.0, 0.0, 0.0]],
        actions=["stop"],
        timesteps=[EpisodeTimestep(
            timestep_index=0, timestamp=0.0, agent_pose=[0.0, 0.0, 0.0], action="stop",
        )],
    )


def _write_scene_episode(root: Path, scene_id: str, episode_id: str) -> SceneDatasetPaths:
    paths = SceneDatasetPaths.from_project(root, scene_id).ensure_layout()
    episode = _episode(scene_id, episode_id)
    write_episode(paths.episode_path(episode), episode)
    write_episode_index(paths)
    write_scene_dataset(paths)
    return paths


def test_scene_local_index_and_validation_do_not_scan_other_scene(tmp_path: Path) -> None:
    root = tmp_path / "opticalnav-v0.2"
    a = _write_scene_episode(root, "scene_a", "scene_a_train_000001")
    b = SceneDatasetPaths.from_project(root, "scene_b").ensure_layout()
    write_episode_index(b)
    write_scene_dataset(b)
    # This is intentionally invalid JSON. A scene-A request must never open it.
    broken = b.episodes_dir / "train" / "not_an_episode.json"
    broken.write_text("{not-json", encoding="utf-8")
    # This emulates the pre-v3 project-wide inventory: it must be ignored by
    # every scene-A list/validation path once A has its own workspace.
    legacy_broken = root / "episodes" / "train" / "legacy_not_an_episode.json"
    legacy_broken.parent.mkdir(parents=True)
    legacy_broken.write_text("{not-json", encoding="utf-8")
    catalog = write_project_catalog(root)

    assert catalog["layout_version"] == PROJECT_CATALOG_VERSION
    assert [path.name for path in find_episode_files(root, scene_id="scene_a")] == ["scene_a_train_000001.json"]
    page = page_episode_index(a, limit=100)
    assert page["scene_id"] == "scene_a"
    assert page["total"] == 1
    assert page["episodes"][0]["episode_id"] == "scene_a_train_000001"

    report = validate_dataset(root, scene_id="scene_a")
    assert report.ok
    assert report.episode_count == 1


def test_empty_scene_page_uses_its_tiny_index_not_legacy_project_inventory(tmp_path: Path) -> None:
    root = tmp_path / "opticalnav-v0.2"
    empty = SceneDatasetPaths.from_project(root, "scene_empty").ensure_layout()
    write_episode_index(empty)
    write_scene_dataset(empty)
    # If the selected scene still consulted the legacy root episode directory,
    # this corrupt payload would make the request fail (and large projects
    # would still block on a complete directory scan).
    legacy = root / "episodes" / "train" / "unrelated.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("{not-json", encoding="utf-8")

    page = page_episode_index(empty, limit=100)
    assert page == {
        "layout_version": "opticalnav_scene_workspace_v3",
        "scene_id": "scene_empty",
        "total": 0,
        "next_cursor": None,
        "episodes": [],
    }


def test_graph_build_preserves_existing_graph_without_explicit_rebuild(tmp_path: Path) -> None:
    root = tmp_path / "opticalnav-v0.2"
    paths = SceneDatasetPaths.from_project(root, "scene_graph").ensure_layout()
    graph = paths.scene_dir / "viewpoint_graph.json"
    original = b'{"graph_id":"manual_400_node_revision","nodes":[1,2,3]}'
    graph.write_bytes(original)

    cmd_graph_build(SimpleNamespace(
        dataset=str(root), scene_id="scene_graph", rebuild_graph=False,
    ))

    assert graph.read_bytes() == original
    assert not list(paths.graph_revisions_dir.glob("*.json"))


def test_migration_moves_legacy_episodes_into_scene_workspaces_and_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "opticalnav-v0.2"
    (root / "scenes" / "scene_a").mkdir(parents=True)
    (root / "scenes" / "scene_b").mkdir(parents=True)
    graph_payload = b'{"nodes":[{"id":"preserved"}],"edges":[]}'
    (root / "scenes" / "scene_a" / "viewpoint_graph.json").write_bytes(graph_payload)
    (root / "episodes" / "train").mkdir(parents=True)
    write_episode(root / "episodes" / "train" / "scene_a_train_000001.json", _episode("scene_a", "scene_a_train_000001"))
    write_episode(root / "episodes" / "train" / "scene_b_train_000001.json", _episode("scene_b", "scene_b_train_000001"))
    (root / "dataset.json").write_text(json.dumps({"project_name": "legacy"}), encoding="utf-8")

    dry = migrate_scene_layout(root, dry_run=True)
    assert dry["legacy_episode_count"] == 2
    result = migrate_scene_layout(root)
    assert result["legacy_episode_count"] == 2
    assert not (root / "episodes").exists()
    assert (root / "scenes" / "scene_a" / "episodes" / "train" / "scene_a_train_000001.json").is_file()
    assert (root / "scenes" / "scene_b" / "episodes" / "train" / "scene_b_train_000001.json").is_file()
    assert json.loads((root / "dataset.json").read_text(encoding="utf-8"))["layout_version"] == PROJECT_CATALOG_VERSION
    assert (root / result["archive_root"] / "episodes" / "train" / "scene_a_train_000001.json").is_file()
    revisions = list((root / "scenes" / "scene_a" / "operations" / "graph_revisions").glob("*_before_scene_layout_v3.json"))
    assert len(revisions) == 1
    assert revisions[0].read_bytes() == graph_payload
    assert result["graph_revisions"]["scene_a"].endswith(revisions[0].name)

    repeated = migrate_scene_layout(root)
    assert repeated["already_migrated"] is True
