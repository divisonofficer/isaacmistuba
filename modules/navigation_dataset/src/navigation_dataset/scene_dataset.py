"""Authoritative scene-local OpticalNav dataset workspace helpers.

Version 3 makes a scene the normal unit of storage and execution.  Code that
has selected a scene must use :class:`SceneDatasetPaths` instead of walking a
project's legacy ``episodes/`` directory.  The resolver deliberately exposes
only paths underneath ``scenes/<scene_id>/`` (plus explicitly shared assets at
the caller) so a scene screen cannot accidentally turn into a project-wide
filesystem scan.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
from typing import Any, Iterable, Iterator
import zipfile

from .episode_schema import EpisodeManifest, SPLITS, read_episode, write_episode


SCENE_LAYOUT_VERSION = "opticalnav_scene_workspace_v3"
PROJECT_CATALOG_VERSION = "opticalnav_project_catalog_v3"
_SAFE_SCENE_COMPONENTS = {".", "..", ""}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_scene_id(scene_id: str) -> str:
    value = str(scene_id).strip()
    path = PurePosixPath(value)
    if value in _SAFE_SCENE_COMPONENTS or path.is_absolute() or len(path.parts) != 1 or "\\" in value:
        raise ValueError(f"scene_id must be a single relative path component, got {scene_id!r}")
    return value


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
    return path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class SceneDatasetPaths:
    """The only canonical resolver for scene-private dataset state.

    ``project_root`` is the directory containing the project catalog.  This
    class intentionally does not offer a project-wide episode iterator.
    Explicit multi-scene orchestration belongs in a caller which instantiates
    one resolver per supplied scene id.
    """

    project_root: Path
    scene_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_root", Path(self.project_root).resolve())
        object.__setattr__(self, "scene_id", _validate_scene_id(self.scene_id))

    @classmethod
    def from_project(cls, project_root: str | Path, scene_id: str) -> "SceneDatasetPaths":
        return cls(Path(project_root), scene_id)

    @property
    def scene_dir(self) -> Path:
        return self.project_root / "scenes" / self.scene_id

    @property
    def dataset_path(self) -> Path:
        return self.scene_dir / "dataset.json"

    @property
    def episode_index_path(self) -> Path:
        return self.scene_dir / "episode_index.json"

    @property
    def episodes_dir(self) -> Path:
        return self.scene_dir / "episodes"

    @property
    def splits_dir(self) -> Path:
        return self.scene_dir / "splits"

    @property
    def observations_dir(self) -> Path:
        return self.scene_dir / "observations"

    @property
    def operations_dir(self) -> Path:
        return self.scene_dir / "operations"

    @property
    def ledger_path(self) -> Path:
        return self.operations_dir / "render_ledger.sqlite3"

    @property
    def graph_render_batches_dir(self) -> Path:
        return self.operations_dir / "graph_render_batches"

    @property
    def render_batches_dir(self) -> Path:
        return self.operations_dir / "render_batches"

    @property
    def exports_dir(self) -> Path:
        return self.operations_dir / "exports"

    @property
    def graph_revisions_dir(self) -> Path:
        return self.operations_dir / "graph_revisions"

    def ensure_layout(self) -> "SceneDatasetPaths":
        for path in (
            self.scene_dir,
            self.episodes_dir,
            self.splits_dir,
            self.observations_dir,
            self.operations_dir,
            self.graph_render_batches_dir,
            self.render_batches_dir,
            self.exports_dir,
            self.graph_revisions_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        for split in SPLITS:
            (self.episodes_dir / split).mkdir(parents=True, exist_ok=True)
        return self

    def episode_path(self, episode: EpisodeManifest) -> Path:
        if str(episode.scene_id) != self.scene_id:
            raise ValueError(
                f"episode {episode.episode_id!r} belongs to {episode.scene_id!r}, not scene {self.scene_id!r}"
            )
        if episode.split not in SPLITS:
            raise ValueError(f"unsupported split: {episode.split!r}")
        return self.episodes_dir / episode.split / f"{episode.episode_id}.json"

    def episode_paths(self, *, split: str | None = None) -> list[Path]:
        if split is not None and split not in SPLITS:
            raise ValueError(f"unsupported split: {split!r}")
        directories = (self.episodes_dir / split,) if split else tuple(self.episodes_dir / item for item in SPLITS)
        return [path for directory in directories for path in sorted(directory.glob("*.json"))]

    def find_episode(self, episode_id: str) -> Path | None:
        name = f"{str(episode_id)}.json"
        matches = [self.episodes_dir / split / name for split in SPLITS if (self.episodes_dir / split / name).is_file()]
        if len(matches) > 1:
            raise ValueError(f"episode {episode_id!r} appears in multiple scene-local splits")
        return matches[0] if matches else None

    def write_episode(self, episode: EpisodeManifest) -> Path:
        self.ensure_layout()
        return write_episode(self.episode_path(episode), episode)

    def iter_episodes(self, *, split: str | None = None) -> Iterator[tuple[Path, EpisodeManifest]]:
        for path in self.episode_paths(split=split):
            episode = read_episode(path)
            if episode.scene_id != self.scene_id:
                raise ValueError(
                    f"scene-local episode path contains scene_id {episode.scene_id!r}: {path}"
                )
            yield path, episode


def _episode_index_record(paths: SceneDatasetPaths, path: Path, episode: EpisodeManifest) -> dict[str, Any]:
    return {
        "episode_id": episode.episode_id,
        "scene_id": paths.scene_id,
        "split": episode.split,
        "navigation_mode": episode.navigation_mode,
        "graph_id": episode.graph_id,
        "start_node": episode.start_node,
        "goal_node": episode.goal_node,
        "path_length": len(episode.path_nodes),
        "timestep_count": len(episode.timesteps),
        "revision": str(episode.metadata.get("graph_revision") or episode.metadata.get("revision") or ""),
        "episode_ref": path.relative_to(paths.scene_dir).as_posix(),
        "sha256": file_sha256(path),
    }


def build_episode_index(paths: SceneDatasetPaths) -> dict[str, Any]:
    """Read only the selected scene's episode files and build its compact index."""
    records = [
        _episode_index_record(paths, path, episode)
        for path, episode in paths.iter_episodes()
    ]
    records.sort(key=lambda item: (str(item["split"]), str(item["episode_id"])))
    split_counts = {split: sum(item["split"] == split for item in records) for split in SPLITS}
    digest = hashlib.sha256(
        json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "layout_version": SCENE_LAYOUT_VERSION,
        "scene_id": paths.scene_id,
        "generated_at": _utc_now(),
        "total": len(records),
        "split_counts": split_counts,
        "digest": digest,
        "episodes": records,
    }


def write_episode_index(paths: SceneDatasetPaths) -> dict[str, Any]:
    paths.ensure_layout()
    payload = build_episode_index(paths)
    _atomic_json_write(paths.episode_index_path, payload)
    for split in SPLITS:
        _atomic_json_write(
            paths.splits_dir / f"{split}.json",
            {
                "layout_version": SCENE_LAYOUT_VERSION,
                "scene_id": paths.scene_id,
                "split": split,
                "episodes": [item["episode_ref"] for item in payload["episodes"] if item["split"] == split],
            },
        )
    return payload


def read_episode_index(paths: SceneDatasetPaths) -> dict[str, Any]:
    if not paths.episode_index_path.is_file():
        return write_episode_index(paths)
    payload = json.loads(paths.episode_index_path.read_text(encoding="utf-8"))
    if payload.get("layout_version") != SCENE_LAYOUT_VERSION or payload.get("scene_id") != paths.scene_id:
        raise ValueError(f"invalid scene-local episode index: {paths.episode_index_path}")
    return payload


def page_episode_index(
    paths: SceneDatasetPaths,
    *,
    split: str | None = None,
    cursor: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Return a stable, bounded page without opening episode manifests."""
    if split is not None and split not in SPLITS:
        raise ValueError(f"unsupported split: {split!r}")
    if limit < 1 or limit > 250:
        raise ValueError("limit must be between 1 and 250")
    index = read_episode_index(paths)
    records = [record for record in index["episodes"] if split is None or record["split"] == split]
    start = 0
    if cursor:
        try:
            start = int(cursor)
        except ValueError as exc:
            raise ValueError("cursor must be an integer offset") from exc
        if start < 0 or start > len(records):
            raise ValueError("cursor out of range")
    page = records[start:start + limit]
    next_cursor = str(start + len(page)) if start + len(page) < len(records) else None
    return {
        "layout_version": SCENE_LAYOUT_VERSION,
        "scene_id": paths.scene_id,
        "total": len(records),
        "next_cursor": next_cursor,
        "episodes": page,
    }


def scene_dataset_payload(paths: SceneDatasetPaths, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    index = read_episode_index(paths)
    return {
        "layout_version": SCENE_LAYOUT_VERSION,
        "scene_id": paths.scene_id,
        "episode_index_ref": (paths.episode_index_path.relative_to(paths.scene_dir)).as_posix(),
        "operations": {
            "ledger_ref": "operations/render_ledger.sqlite3",
            "graph_render_batches_ref": "operations/graph_render_batches",
            "render_batches_ref": "operations/render_batches",
            "exports_ref": "operations/exports",
            "graph_revisions_ref": "operations/graph_revisions",
        },
        "episode_count": index["total"],
        "split_counts": index["split_counts"],
        "episode_digest": index["digest"],
        "updated_at": _utc_now(),
        "metadata": dict(metadata or {}),
    }


def write_scene_dataset(paths: SceneDatasetPaths, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    paths.ensure_layout()
    payload = scene_dataset_payload(paths, metadata=metadata)
    _atomic_json_write(paths.dataset_path, payload)
    return payload


def snapshot_graph_revision(paths: SceneDatasetPaths, graph_path: str | Path, *, reason: str) -> Path:
    """Preserve a complete graph payload before an explicit replacement.

    We retain the original JSON byte-for-byte and place a small sidecar beside
    it.  This is intentionally not an attempt to synthesize a graph from edit
    history: without a complete source payload such reconstruction is unsafe.
    """
    source = Path(graph_path)
    if not source.is_file():
        raise FileNotFoundError(source)
    paths.ensure_layout()
    timestamp = _utc_now().replace(":", "").replace("-", "")
    digest = file_sha256(source)
    output = paths.graph_revisions_dir / f"{timestamp}_{digest[:12]}_before_{reason}.json"
    with source.open("rb") as handle:
        payload = handle.read()
    fd, tmp_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, output)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
    _atomic_json_write(output.with_suffix(".metadata.json"), {
        "layout_version": SCENE_LAYOUT_VERSION,
        "scene_id": paths.scene_id,
        "reason": reason,
        "source_ref": source.relative_to(paths.project_root).as_posix(),
        "sha256": digest,
        "created_at": _utc_now(),
    })
    return output


def write_project_catalog(project_root: str | Path) -> dict[str, Any]:
    """Create the compact project catalog from scene manifests only.

    This is intentionally the sole project-wide scene glob.  It is a catalog
    update operation, never called by scene-local list/render/export routes.
    """
    root = Path(project_root).resolve()
    entries: list[dict[str, Any]] = []
    for dataset_path in sorted((root / "scenes").glob("*/dataset.json")):
        try:
            payload = json.loads(dataset_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if payload.get("layout_version") != SCENE_LAYOUT_VERSION:
            continue
        scene_id = str(payload.get("scene_id") or "")
        if not scene_id:
            continue
        entries.append({
            "scene_id": scene_id,
            "dataset_ref": dataset_path.relative_to(root).as_posix(),
            "episode_count": int(payload.get("episode_count") or 0),
            "split_counts": dict(payload.get("split_counts") or {}),
            "episode_digest": str(payload.get("episode_digest") or ""),
            "status": str(payload.get("status") or (payload.get("metadata") or {}).get("status") or "ready"),
            "updated_at": str(payload.get("updated_at") or ""),
        })
    entries.sort(key=lambda item: item["scene_id"])
    catalog_digest = hashlib.sha256(
        json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    payload = {
        "layout_version": PROJECT_CATALOG_VERSION,
        "project_name": root.name,
        "generated_at": _utc_now(),
        "scene_count": len(entries),
        "catalog_digest": catalog_digest,
        "scenes": entries,
    }
    _atomic_json_write(root / "dataset.json", payload)
    return payload


def export_scene_workspace_zip(paths: SceneDatasetPaths, output_zip: str | Path | None = None) -> Path:
    """Archive one complete scene workspace, never its sibling scenes.

    Observation and operation artefacts live below the workspace itself, so the
    resulting archive is self-contained without consulting project-global
    episode, ledger, or batch directories.
    """
    paths.ensure_layout()
    if output_zip is None:
        output = paths.exports_dir / f"{paths.scene_id}.zip"
    else:
        output = Path(output_zip)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(item for item in paths.scene_dir.rglob("*") if item.is_file()):
            if source.resolve() == output.resolve():
                continue
            archive.write(source, source.relative_to(paths.scene_dir).as_posix())
    return output
