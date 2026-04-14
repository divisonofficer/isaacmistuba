from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from .paths import resolve_repo_path, to_repo_relative_posix
from .types import SceneSnapshot


def _shape_basename(shape: ET.Element) -> str | None:
    for string_node in shape.findall("./string"):
        if string_node.attrib.get("name") == "filename":
            return Path(string_node.attrib.get("value", "")).name
    return None


def _candidate_shape_ids_for_mesh(snapshot_mesh, scene_shapes: list[dict[str, Any]]) -> list[str]:
    prim_path = str(snapshot_mesh.source_path)
    prim_name = prim_path.rstrip("/").split("/")[-1] if prim_path else snapshot_mesh.name
    candidates: list[str] = []

    for shape in scene_shapes:
        shape_id = shape.get("shape_id")
        shape_name = shape.get("shape_name")
        basename = shape.get("basename")
        stem = Path(basename).stem if basename else None

        if shape_id in {prim_path, snapshot_mesh.mesh_id, prim_name}:
            candidates.append(shape_id)
            continue
        if shape_name == prim_name or stem == prim_name:
            candidates.append(shape_id)

    deduped: list[str] = []
    seen: set[str] = set()
    for shape_id in candidates:
        if not shape_id or shape_id in seen:
            continue
        seen.add(shape_id)
        deduped.append(shape_id)
    return deduped


def build_shape_mapping(snapshot: SceneSnapshot, scene_xml: str | Path) -> dict[str, Any]:
    scene_path = Path(scene_xml)
    root = ET.parse(scene_path).getroot()
    scene_shapes: list[dict[str, Any]] = []
    for index, shape in enumerate(root.findall("./shape")):
        shape_id = shape.attrib.get("id") or f"shape_{index:04d}"
        scene_shapes.append(
            {
                "shape_id": shape_id,
                "shape_name": shape.attrib.get("id"),
                "basename": _shape_basename(shape),
            }
        )

    prim_to_shape_ids: dict[str, list[str]] = {}
    unmatched_prim_paths: list[str] = []
    for mesh in snapshot.meshes:
        matches = _candidate_shape_ids_for_mesh(mesh, scene_shapes)
        if matches:
            prim_to_shape_ids[mesh.source_path] = matches
        else:
            unmatched_prim_paths.append(mesh.source_path)

    return {
        "scene_id": snapshot.scene_id,
        "prim_to_shape_ids": prim_to_shape_ids,
        "unmatched_prim_paths": unmatched_prim_paths,
        "shape_count": len(scene_shapes),
    }


def write_shape_mapping(
    path: str | Path,
    *,
    mapping_payload: dict[str, Any],
    repo_root: str | Path | None = None,
    scene_xml_ref: str | None = None,
    scene_snapshot_ref: str | None = None,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(mapping_payload)
    if repo_root is not None:
        repo_path = Path(repo_root).resolve()
        payload["shape_map_ref"] = to_repo_relative_posix(repo_path, output.resolve())
    if scene_xml_ref is not None:
        payload["mitsuba_scene_ref"] = scene_xml_ref
    if scene_snapshot_ref is not None:
        payload["scene_snapshot_ref"] = scene_snapshot_ref
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def read_shape_mapping(path: str | Path, *, repo_root: str | Path | None = None) -> dict[str, Any]:
    candidate = Path(path)
    if repo_root is not None:
        candidate = resolve_repo_path(Path(repo_root).resolve(), str(path))
    return json.loads(candidate.read_text(encoding="utf-8"))
