from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .episode_schema import read_episode
from .exporters.custom_json import find_episode_files
from .scene_dataset import SceneDatasetPaths
from .scene_annotations import read_scene_annotation
from .viewpoint_graph import read_viewpoint_graph


@dataclass
class ValidationReport:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    episode_count: int = 0
    scene_ids: list[str] | None = None

    def to_payload(self) -> dict:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "episode_count": self.episode_count,
            "scene_ids": list(self.scene_ids) if self.scene_ids is not None else None,
        }


def _artifact_exists(root: Path, ref: object) -> bool:
    if not ref:
        return False
    value = str(ref)
    candidates = [root / value, Path(value)]
    if len(root.parents) >= 3:
        candidates.append(root.parents[2] / value)
    return any(candidate.exists() for candidate in candidates)


def validate_dataset(
    dataset_root: str | Path,
    *,
    require_observations: bool = False,
    scene_ids: Iterable[str] | None = None,
    scene_id: str | None = None,
) -> ValidationReport:
    root = Path(dataset_root)
    errors: list[str] = []
    warnings: list[str] = []
    if scene_id is not None and scene_ids is not None:
        raise ValueError("pass scene_id or scene_ids, not both")
    scene_filter = ({str(scene_id)} if scene_id is not None else
                    (set(str(sid) for sid in scene_ids) if scene_ids is not None else None))
    if not (root / "dataset.json").exists():
        warnings.append("dataset.json is missing; run opticalnav export or write_dataset_index.")
    annotation_paths = (
        [root / "scenes" / str(scene_id) / "scene_annotation.json"]
        if scene_id is not None else sorted((root / "scenes").glob("*/scene_annotation.json"))
    )
    for annotation_path in annotation_paths:
        if not annotation_path.exists():
            continue
        try:
            annotation = read_scene_annotation(annotation_path)
        except Exception as exc:
            errors.append(f"{annotation_path}: {type(exc).__name__}: {exc}")
            continue
        if scene_filter is not None and annotation.scene_id not in scene_filter:
            continue
        sync = dict(annotation.metadata.get("sync", {}))
        if sync.get("render_scene") == "pending":
            warnings.append(f"{annotation.scene_id}: render scene sync is pending.")
        if sync.get("isaac_stage") == "pending":
            warnings.append(f"{annotation.scene_id}: Isaac stage sync is pending.")
        if sync.get("render_scene") == "blocked":
            errors.append(f"{annotation.scene_id}: render readiness is blocked; run Sync Render Scene and resolve readiness errors.")
        if sync.get("render_scene") == "synced":
            for key in ("scene_variant_ref", "render_scene_overlay_ref", "render_scene_xml_ref", "render_readiness_ref"):
                ref = sync.get(key)
                if not ref:
                    errors.append(f"{annotation.scene_id}: sync.{key} is required when render_scene is synced.")
                elif not _artifact_exists(root, ref):
                    errors.append(f"{annotation.scene_id}: missing synced render-scene artifact {ref}")
            readiness_ref = sync.get("render_readiness_ref")
            if readiness_ref and _artifact_exists(root, readiness_ref):
                import json
                readiness_path = root / str(readiness_ref)
                if not readiness_path.exists() and len(root.parents) >= 3:
                    readiness_path = root.parents[2] / str(readiness_ref)
                try:
                    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
                    if readiness.get("ok") is False:
                        errors.append(f"{annotation.scene_id}: render readiness is blocked.")
                except Exception as exc:
                    errors.append(f"{annotation.scene_id}: render readiness cannot be read: {exc}")
    graph_paths = (
        [root / "scenes" / str(scene_id) / "viewpoint_graph.json"]
        if scene_id is not None else sorted((root / "scenes").glob("*/viewpoint_graph.json"))
    )
    for graph_path in graph_paths:
        if not graph_path.exists():
            continue
        try:
            graph = read_viewpoint_graph(graph_path)
        except Exception as exc:
            errors.append(f"{graph_path}: {type(exc).__name__}: {exc}")
            continue
        if scene_filter is not None and graph.scene_id not in scene_filter:
            continue
        for node in graph.nodes:
            for heading in node.headings:
                for modality, ref in heading.sensor_observations.items():
                    if require_observations and not ref:
                        errors.append(f"{graph.graph_id}/{node.node_id}/{heading.heading_id}/{modality}: missing observation ref")
                    if ref and not (root / ref).exists():
                        errors.append(f"{graph.graph_id}/{node.node_id}/{heading.heading_id}/{modality}: missing observation bundle {ref}")
    if scene_id is not None:
        # The scene-local resolver is deliberately used before any legacy glob:
        # an invalid or enormous episode directory in another scene cannot
        # affect this validation request.
        all_episode_paths = SceneDatasetPaths.from_project(root, scene_id).episode_paths()
    else:
        all_episode_paths = find_episode_files(root)
    episode_paths: list[Path] = []
    for episode_path in all_episode_paths:
        try:
            episode = read_episode(episode_path)
        except Exception as exc:
            errors.append(f"{episode_path}: {type(exc).__name__}: {exc}")
            continue
        if scene_filter is not None and episode.scene_id not in scene_filter:
            continue
        episode_paths.append(episode_path)
        for timestep in episode.timesteps:
            if require_observations and not timestep.observation_bundle_ref:
                errors.append(f"{episode.episode_id}[{timestep.timestep_index}]: missing observation_bundle_ref")
            if timestep.observation_bundle_ref and not (root / timestep.observation_bundle_ref).exists():
                errors.append(f"{episode.episode_id}[{timestep.timestep_index}]: missing observation bundle {timestep.observation_bundle_ref}")
        for ref in episode.observation_refs:
            if require_observations and not (root / ref).exists():
                errors.append(f"{episode.episode_id}: missing cached graph observation {ref}")
    if not episode_paths:
        msg = "No episode JSON files found."
        if scene_filter is not None:
            msg += f" (scope: {sorted(scene_filter)})"
        warnings.append(msg)
    return ValidationReport(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        episode_count=len(episode_paths),
        scene_ids=sorted(scene_filter) if scene_filter is not None else None,
    )
