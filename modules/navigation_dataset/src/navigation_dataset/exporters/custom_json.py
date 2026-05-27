from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import zipfile

from ..episode_schema import DatasetProject, EpisodeManifest, read_episode, read_project, write_project


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def find_episode_files(dataset_root: str | Path) -> list[Path]:
    root = Path(dataset_root)
    return sorted((root / "episodes").glob("*/*.json"))


def build_dataset_index(dataset_root: str | Path) -> dict:
    root = Path(dataset_root).resolve()
    project_path = root / "dataset.json"
    project = read_project(project_path) if project_path.exists() else DatasetProject(project_name=root.name)
    episodes_by_split: dict[str, list[str]] = {"train": [], "val_seen": [], "val_unseen": [], "test": []}
    scene_ids: set[str] = set()
    for path in find_episode_files(root):
        episode = read_episode(path)
        episodes_by_split.setdefault(episode.split, []).append(_rel(root, path))
        scene_ids.add(episode.scene_id)
    scene_artifacts: list[dict] = []
    for scene_dir in sorted((root / "scenes").glob("*")):
        if not scene_dir.is_dir():
            continue
        entry = {"scene_id": scene_dir.name}
        for filename, field_name in (
            ("authoring_map.json", "authoring_map_ref"),
            ("scene_annotation.json", "annotation_ref"),
            ("scene_variant.json", "scene_variant_ref"),
            ("render_scene_overlays.json", "render_scene_overlay_ref"),
            ("traversable_grid.npy", "traversable_grid_ref"),
            ("nav_graph.json", "nav_graph_ref"),
            ("viewpoint_graph.json", "viewpoint_graph_ref"),
        ):
            path = scene_dir / filename
            if path.exists():
                entry[field_name] = _rel(root, path)
        scene_artifacts.append(entry)
        scene_ids.add(scene_dir.name)
    return {
        **asdict(project),
        "scenes": sorted(scene_ids),
        "scene_artifacts": scene_artifacts,
        "splits": episodes_by_split,
        "episode_count": sum(len(items) for items in episodes_by_split.values()),
        "format": "custom_json",
    }


def write_dataset_index(dataset_root: str | Path) -> Path:
    root = Path(dataset_root)
    index = build_dataset_index(root)
    path = root / "dataset.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_split_files(dataset_root: str | Path) -> list[Path]:
    root = Path(dataset_root)
    index = build_dataset_index(root)
    output_dir = root / "splits"
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for split, episodes in index["splits"].items():
        path = output_dir / f"{split}.json"
        path.write_text(json.dumps({"split": split, "episodes": episodes}, indent=2), encoding="utf-8")
        paths.append(path)
    return paths


def export_dataset_zip(dataset_root: str | Path, output_zip: str | Path | None = None) -> Path:
    root = Path(dataset_root).resolve()
    write_dataset_index(root)
    write_split_files(root)
    zip_path = Path(output_zip) if output_zip is not None else root.with_suffix(".zip")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            zf.write(path, _rel(root, path))
    return zip_path
