from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .episode_schema import read_episode
from .exporters.custom_json import find_episode_files
from .scene_annotations import read_scene_annotation
from .viewpoint_graph import read_viewpoint_graph


@dataclass
class ValidationReport:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    episode_count: int = 0

    def to_payload(self) -> dict:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "episode_count": self.episode_count,
        }


def validate_dataset(dataset_root: str | Path, *, require_observations: bool = False) -> ValidationReport:
    root = Path(dataset_root)
    errors: list[str] = []
    warnings: list[str] = []
    if not (root / "dataset.json").exists():
        warnings.append("dataset.json is missing; run opticalnav export or write_dataset_index.")
    for annotation_path in sorted((root / "scenes").glob("*/scene_annotation.json")):
        try:
            annotation = read_scene_annotation(annotation_path)
        except Exception as exc:
            errors.append(f"{annotation_path}: {type(exc).__name__}: {exc}")
            continue
        sync = dict(annotation.metadata.get("sync", {}))
        if sync.get("render_scene") == "pending":
            warnings.append(f"{annotation.scene_id}: render scene sync is pending.")
        if sync.get("isaac_stage") == "pending":
            warnings.append(f"{annotation.scene_id}: Isaac stage sync is pending.")
        if sync.get("render_scene") == "synced":
            for key in ("scene_variant_ref", "render_scene_overlay_ref"):
                ref = sync.get(key)
                if not ref:
                    errors.append(f"{annotation.scene_id}: sync.{key} is required when render_scene is synced.")
                elif not (root / str(ref)).exists():
                    errors.append(f"{annotation.scene_id}: missing synced render-scene artifact {ref}")
    for graph_path in sorted((root / "scenes").glob("*/viewpoint_graph.json")):
        try:
            graph = read_viewpoint_graph(graph_path)
        except Exception as exc:
            errors.append(f"{graph_path}: {type(exc).__name__}: {exc}")
            continue
        for node in graph.nodes:
            for heading in node.headings:
                for modality, ref in heading.sensor_observations.items():
                    if require_observations and not ref:
                        errors.append(f"{graph.graph_id}/{node.node_id}/{heading.heading_id}/{modality}: missing observation ref")
                    if ref and not (root / ref).exists():
                        errors.append(f"{graph.graph_id}/{node.node_id}/{heading.heading_id}/{modality}: missing observation bundle {ref}")
    episode_paths = find_episode_files(root)
    for episode_path in episode_paths:
        try:
            episode = read_episode(episode_path)
        except Exception as exc:
            errors.append(f"{episode_path}: {type(exc).__name__}: {exc}")
            continue
        for timestep in episode.timesteps:
            if require_observations and not timestep.observation_bundle_ref:
                errors.append(f"{episode.episode_id}[{timestep.timestep_index}]: missing observation_bundle_ref")
            if timestep.observation_bundle_ref and not (root / timestep.observation_bundle_ref).exists():
                errors.append(f"{episode.episode_id}[{timestep.timestep_index}]: missing observation bundle {timestep.observation_bundle_ref}")
        for ref in episode.observation_refs:
            if require_observations and not (root / ref).exists():
                errors.append(f"{episode.episode_id}: missing cached graph observation {ref}")
    if not episode_paths:
        warnings.append("No episode JSON files found.")
    return ValidationReport(ok=not errors, errors=errors, warnings=warnings, episode_count=len(episode_paths))
