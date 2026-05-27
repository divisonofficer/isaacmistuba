from __future__ import annotations

from pathlib import Path
import hashlib
from typing import Any, Mapping

import numpy as np

from .multimodal import normalize_mat4_storage


JsonDict = dict[str, Any]


def _category_for(name: str, source_path: str, material_id: str | None = None) -> str:
    key = " ".join([name, source_path, str(material_id or "")]).lower()
    if any(token in key for token in ("floor", "ground", "slab", "tile", "woodfloor")):
        return "floor"
    if any(token in key for token in ("glass", "transparent", "window", "pane")):
        return "glass"
    if any(token in key for token in ("mirror", "reflect")):
        return "mirror"
    if any(token in key for token in ("wall", "door", "beam", "partition", "shell")):
        return "shell"
    if any(token in key for token in ("chair", "table", "desk", "cabinet", "sofa", "shelf", "plant", "furniture")):
        return "furniture"
    return "object"


def _material_hint(category: str) -> str:
    if category == "glass":
        return "clear_glass"
    if category == "mirror":
        return "mirror"
    if category == "floor":
        return "tile"
    if category == "furniture":
        return "wood"
    return "painted_wall"


def _bounds_payload(points: np.ndarray) -> JsonDict:
    mn = points[:, :3].min(axis=0)
    mx = points[:, :3].max(axis=0)
    size = np.maximum(mx - mn, 1e-4)
    center = (mn + mx) * 0.5
    return {
        "min": mn.astype(float).tolist(),
        "max": mx.astype(float).tolist(),
        "size": size.astype(float).tolist(),
        "center": center.astype(float).tolist(),
    }


def _world_vertices(vertices: Any, transform: Any) -> np.ndarray | None:
    if not vertices:
        return None
    try:
        pts = np.asarray(vertices, dtype=np.float32)
    except Exception:
        return None
    if pts.ndim != 2 or pts.shape[1] < 3 or pts.shape[0] == 0:
        return None
    matrix = np.eye(4, dtype=np.float32)
    if isinstance(transform, list) and len(transform) == 16:
        try:
            matrix = normalize_mat4_storage(transform).astype(np.float32)
        except Exception:
            matrix = np.eye(4, dtype=np.float32)
    hom = np.concatenate([pts[:, :3], np.ones((pts.shape[0], 1), dtype=np.float32)], axis=1)
    return (hom @ matrix.T)[:, :3]


def _stable_id(source_path: str, index: int) -> str:
    digest = hashlib.sha1(f"{source_path}:{index}".encode("utf-8")).hexdigest()[:10]
    return f"usd_obj_{digest}"


def build_editor_geometry_from_snapshot(snapshot: Any, *, scene_id: str, usd_ref: str | None = None) -> JsonDict:
    objects: list[JsonDict] = []
    floor_planes: list[JsonDict] = []
    scene_points: list[np.ndarray] = []

    for index, mesh in enumerate(getattr(snapshot, "meshes", []) or []):
        if getattr(mesh, "visible", True) is False:
            continue
        geometry = getattr(mesh, "extras", {}).get("geometry") if isinstance(getattr(mesh, "extras", None), Mapping) else None
        vertices = geometry.get("vertices") if isinstance(geometry, Mapping) else None
        world = _world_vertices(vertices, getattr(mesh, "transform", None))
        if world is None:
            continue
        bounds = _bounds_payload(world)
        name = str(getattr(mesh, "name", "") or getattr(mesh, "mesh_id", "") or "mesh")
        source_path = str(getattr(mesh, "source_path", "") or name)
        material_id = getattr(mesh, "material_id", None)
        category = _category_for(name, source_path, material_id)
        record = {
            "id": _stable_id(source_path, index),
            "source_path": source_path,
            "label": name.rsplit("/", 1)[-1] or name,
            "category": category,
            "material_hint": _material_hint(category),
            "bounds": bounds,
            "proxy": {"type": "box"},
            "vertex_count": int(getattr(mesh, "vertex_count", 0) or len(world)),
            "face_count": int(getattr(mesh, "face_count", 0) or 0),
        }
        objects.append(record)
        if category == "floor":
            floor_planes.append({"id": f"floor_{len(floor_planes) + 1:03d}", "source_path": source_path, "bounds": bounds})
        scene_points.append(world[:, :3].min(axis=0))
        scene_points.append(world[:, :3].max(axis=0))

    if scene_points:
        bounds = _bounds_payload(np.vstack(scene_points))
    else:
        bounds = {"min": [0.0, 0.0, 0.0], "max": [6.0, 0.1, 4.0], "size": [6.0, 0.1, 4.0], "center": [3.0, 0.05, 2.0]}
    if not floor_planes:
        mn = bounds["min"]
        mx = bounds["max"]
        floor_planes.append({
            "id": "floor_fallback",
            "bounds": {"min": [mn[0], 0.0, mn[2]], "max": [mx[0], 0.05, mx[2]], "size": [mx[0] - mn[0], 0.05, mx[2] - mn[2]], "center": [(mn[0] + mx[0]) * 0.5, 0.025, (mn[2] + mx[2]) * 0.5]},
        })
    return {
        "scene_id": scene_id,
        "status": "ready",
        "usd_ref": usd_ref,
        "coordinate_system": "world_xz_authoring",
        "simplification_mode": "proxy_bounds_v1",
        "bounds": bounds,
        "objects": objects,
        "floor_planes": floor_planes,
    }


def build_usd_editor_geometry(usd_path: str | Path, *, scene_id: str, repo_root: str | Path | None = None, usd_ref: str | None = None) -> JsonDict:
    from .usd_snapshot import extract_snapshot_from_usd

    extracted = extract_snapshot_from_usd(str(usd_path), scene_id=scene_id, repo_root=repo_root, include_geometry_payloads=True)
    return build_editor_geometry_from_snapshot(extracted.snapshot, scene_id=scene_id, usd_ref=usd_ref)
