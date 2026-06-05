from __future__ import annotations

from pathlib import Path
import hashlib
from typing import Any, Mapping

import numpy as np

from .multimodal import normalize_mat4_storage


JsonDict = dict[str, Any]


def _stage_meters_per_unit(stage: Any) -> float:
    from pxr import UsdGeom  # type: ignore

    try:
        value = float(UsdGeom.GetStageMetersPerUnit(stage))
        if 1e-6 < value < 1e3:
            return value
    except Exception:
        pass
    return 1.0


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
        return "curated:glass_clear"
    if category == "mirror":
        return "mirror"
    if category == "floor":
        return "pbrdf_2020:ceramic_alumina"
    if category == "furniture":
        return "pbrdf_2020:peek"
    return "pbrdf_2020:white_billiard"


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


def _bounds_payload_from_min_max(mn_raw: Any, mx_raw: Any, *, scale: float = 1.0) -> JsonDict | None:
    try:
        mn = np.asarray([float(mn_raw[0]), float(mn_raw[1]), float(mn_raw[2])], dtype=np.float64) * scale
        mx = np.asarray([float(mx_raw[0]), float(mx_raw[1]), float(mx_raw[2])], dtype=np.float64) * scale
    except Exception:
        return None
    if not np.all(np.isfinite(mn)) or not np.all(np.isfinite(mx)):
        return None
    size = mx - mn
    if np.any(size < -1e-6):
        return None
    size = np.maximum(size, 1e-4)
    center = (mn + mx) * 0.5
    return {
        "min": mn.astype(float).tolist(),
        "max": mx.astype(float).tolist(),
        "size": size.astype(float).tolist(),
        "center": center.astype(float).tolist(),
    }


def _is_useful_bounds(bounds: JsonDict) -> bool:
    size = bounds.get("size") or []
    if len(size) < 3:
        return False
    sx, sy, sz = (float(size[0]), float(size[1]), float(size[2]))
    if sx <= 1e-4 or sy <= 1e-4 or sz <= 1e-4:
        return False
    if sx > 5000 or sy > 5000 or sz > 5000:
        return False
    return True


def _looks_like_floor(category: str, bounds: JsonDict) -> bool:
    size = bounds.get("size") or [0, 0, 0]
    try:
        sx, sy, sz = float(size[0]), float(size[1]), float(size[2])
    except Exception:
        return category == "floor"
    return category == "floor" or (sy <= 0.25 and sx >= 1.0 and sz >= 1.0)


def _path_depth(path: str) -> int:
    return len([part for part in path.strip("/").split("/") if part])


def _is_generic_usd_group(name: str, source_path: str) -> bool:
    key = f"{name} {source_path}".lower()
    generic_names = {
        "root",
        "geo",
        "geometry",
        "render",
        "proxy",
        "core",
        "world",
        "scene",
        "materials",
        "looks",
        "cameras",
        "lights",
        "lgt",
    }
    if name.lower() in generic_names:
        return True
    return any(token in key for token in ("/materials", "/cameras", "/lgt", "/lights", "/terrain", "/landscape"))


def _is_scene_scale_container(bounds: JsonDict, mesh_count: int, category: str) -> bool:
    size = bounds.get("size") or [0, 0, 0]
    try:
        sx, sy, sz = float(size[0]), float(size[1]), float(size[2])
    except Exception:
        return True
    horizontal = max(sx, sz)
    if category in {"floor", "shell", "glass", "mirror"}:
        return horizontal > 30.0 or sy > 12.0 or mesh_count > 160
    return horizontal > 8.0 or sy > 5.0 or mesh_count > 80


def _is_assembly_candidate(record: Mapping[str, Any]) -> bool:
    mesh_count = int(record.get("mesh_count", 0) or 0)
    if mesh_count < 2:
        return False
    name = str(record.get("label") or "")
    source_path = str(record.get("source_path") or "")
    category = str(record.get("category") or "object")
    if _path_depth(source_path) <= 2:
        return False
    if _is_generic_usd_group(name, source_path):
        return False
    bounds = record.get("bounds")
    if not isinstance(bounds, Mapping) or _is_scene_scale_container(bounds, mesh_count, category):
        return False
    return True


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


def build_editor_geometry_from_usd_bounds(
    usd_path: str | Path,
    *,
    scene_id: str,
    usd_ref: str | None = None,
    max_objects: int = 800,
) -> JsonDict:
    from pxr import Usd, UsdGeom  # type: ignore

    stage = Usd.Stage.Open(str(usd_path))
    if stage is None:
        raise RuntimeError(f"Could not open USD stage: {usd_path}")
    meters_per_unit = _stage_meters_per_unit(stage)

    bbox_cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(),
        ["default", "render", "proxy"],
        useExtentsHint=True,
    )
    prims = [prim for prim in stage.Traverse() if prim.IsActive() and prim.IsLoaded()]
    mesh_counts: dict[str, int] = {}
    for prim in prims:
        path = str(prim.GetPath())
        mesh_counts[path] = 1 if prim.IsA(UsdGeom.Mesh) else 0
    prim_by_path = {str(prim.GetPath()): prim for prim in prims}
    for path in sorted(prim_by_path, key=_path_depth, reverse=True):
        parent_path = path.rsplit("/", 1)[0] or "/"
        if parent_path in mesh_counts:
            mesh_counts[parent_path] += mesh_counts.get(path, 0)

    records_by_path: dict[str, JsonDict] = {}
    path_order: list[str] = []

    for prim in prims:
        if not prim.IsA(UsdGeom.Imageable):
            continue
        mesh_count = mesh_counts.get(str(prim.GetPath()), 0)
        if mesh_count <= 0:
            continue
        try:
            aligned = bbox_cache.ComputeWorldBound(prim).ComputeAlignedRange()
            if aligned.IsEmpty():
                continue
            bounds = _bounds_payload_from_min_max(aligned.GetMin(), aligned.GetMax(), scale=meters_per_unit)
        except Exception:
            continue
        if bounds is None or not _is_useful_bounds(bounds):
            continue

        source_path = str(prim.GetPath())
        name = prim.GetName() or source_path.rsplit("/", 1)[-1] or "prim"
        category = _category_for(name, source_path)
        record = {
            "id": _stable_id(source_path, len(path_order)),
            "source_path": source_path,
            "label": name,
            "category": category,
            "material_hint": _material_hint(category),
            "bounds": bounds,
            "proxy": {"type": "box"},
            "prim_type": prim.GetTypeName(),
            "mesh_count": int(mesh_count),
            "grouping": "assembly" if mesh_count > 1 else "mesh",
        }
        records_by_path[source_path] = record
        path_order.append(source_path)

    selected_paths: list[str] = []
    selected_set: set[str] = set()
    for path in path_order:
        record = records_by_path[path]
        if any(path.startswith(parent.rstrip("/") + "/") for parent in selected_paths):
            continue
        if _is_assembly_candidate(record) or int(record.get("mesh_count", 0) or 0) == 1:
            selected_paths.append(path)
            selected_set.add(path)

    objects: list[JsonDict] = []
    floor_planes: list[JsonDict] = []
    scene_points: list[np.ndarray] = []
    skipped_after_limit = 0

    for index, source_path in enumerate(selected_paths):
        if len(objects) >= max_objects:
            skipped_after_limit += 1
            continue
        record = records_by_path.get(source_path)
        if not record:
            continue
        bounds = record["bounds"]
        if bounds is None or not _is_useful_bounds(bounds):
            continue

        objects.append(record)
        mn = np.asarray(bounds["min"], dtype=np.float64)
        mx = np.asarray(bounds["max"], dtype=np.float64)
        scene_points.append(mn)
        scene_points.append(mx)
        if _looks_like_floor(str(record.get("category") or "object"), bounds):
            floor_planes.append({
                "id": f"floor_{len(floor_planes) + 1:03d}",
                "source_path": source_path,
                "bounds": bounds,
            })

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
        "simplification_mode": "usd_bbox_assembly_proxy_v3",
        "meters_per_unit": meters_per_unit,
        "bounds": bounds,
        "objects": objects,
        "floor_planes": floor_planes,
        "source_stats": {
            "object_limit": max_objects,
            "truncated": skipped_after_limit > 0,
            "skipped_after_limit": skipped_after_limit,
            "candidate_count": len(records_by_path),
            "selected_count": len(selected_set),
            "grouping": "assembly_preferred",
        },
    }


def build_usd_editor_geometry(usd_path: str | Path, *, scene_id: str, repo_root: str | Path | None = None, usd_ref: str | None = None) -> JsonDict:
    return build_editor_geometry_from_usd_bounds(usd_path, scene_id=scene_id, usd_ref=usd_ref)


def build_usd_editor_geometry_from_snapshot(usd_path: str | Path, *, scene_id: str, repo_root: str | Path | None = None, usd_ref: str | None = None) -> JsonDict:
    from .usd_snapshot import extract_snapshot_from_usd

    extracted = extract_snapshot_from_usd(str(usd_path), scene_id=scene_id, repo_root=repo_root, include_geometry_payloads=True)
    return build_editor_geometry_from_snapshot(extracted.snapshot, scene_id=scene_id, usd_ref=usd_ref)


def extract_prim_mesh_for_editor(
    usd_path: str | Path,
    source_path: str,
    *,
    max_triangles: int = 2000,
    max_mesh_prims: int = 64,
    stage: Any = None,
) -> JsonDict | None:
    """Extract simplified mesh geometry for a USD prim in prim-local space centered at origin.

    Returns vertices (flat float list) + indices (flat int list) suitable for THREE.BufferGeometry,
    or None if the prim has no usable mesh.

    Pass a pre-opened ``stage`` to avoid re-opening large USD files on every call.
    """
    from pxr import Usd, UsdGeom  # type: ignore

    if stage is None:
        stage = Usd.Stage.Open(str(usd_path))
    if stage is None:
        return None

    prim = stage.GetPrimAtPath(source_path)
    if not prim or not prim.IsValid():
        return None

    # metersPerUnit converts USD native units (often cm = 0.01) → meters for Three.js
    try:
        meters_per_unit = float(UsdGeom.GetStageMetersPerUnit(stage))
        if not (1e-6 < meters_per_unit < 1e3):
            meters_per_unit = 1.0
    except Exception:
        meters_per_unit = 1.0

    xform_cache = UsdGeom.XformCache(Usd.TimeCode.Default())

    # Compute inverse of root prim's world transform so sub-mesh vertices
    # are expressed in prim-local space (not scattered world space).
    try:
        prim_world_inv = np.asarray(
            xform_cache.GetLocalToWorldTransform(prim).GetInverse(),
            dtype=np.float64,
        ).reshape(4, 4)
    except Exception:
        prim_world_inv = np.eye(4, dtype=np.float64)

    all_verts: list[np.ndarray] = []
    all_tris: list[np.ndarray] = []
    vertex_offset = 0

    mesh_prims: list[Any] = []
    if prim.IsA(UsdGeom.Mesh):
        mesh_prims = [prim]
    else:
        for child in Usd.PrimRange(prim):
            if child.IsA(UsdGeom.Mesh):
                mesh_prims.append(child)
            if len(mesh_prims) >= max_mesh_prims:
                break

    for mp in mesh_prims:
        mesh_schema = UsdGeom.Mesh(mp)
        points_attr = mesh_schema.GetPointsAttr()
        indices_attr = mesh_schema.GetFaceVertexIndicesAttr()
        counts_attr = mesh_schema.GetFaceVertexCountsAttr()
        if not (points_attr and indices_attr and counts_attr):
            continue
        raw_pts = points_attr.Get()
        raw_idx = indices_attr.Get()
        raw_cnts = counts_attr.Get()
        if raw_pts is None or raw_idx is None or raw_cnts is None:
            continue

        pts = np.asarray(raw_pts, dtype=np.float32)
        idx = np.asarray(raw_idx, dtype=np.int32)
        cnts = np.asarray(raw_cnts, dtype=np.int32)
        if pts.shape[0] == 0:
            continue

        # Transform vertices into prim-local space in meters:
        # p_prim_local_m = p_mesh_local @ M_mesh_to_world @ M_world_to_prim * metersPerUnit
        try:
            mp_world = np.asarray(
                xform_cache.GetLocalToWorldTransform(mp),
                dtype=np.float64,
            ).reshape(4, 4)
            local_to_prim = mp_world @ prim_world_inv
            hom = np.concatenate([pts[:, :3].astype(np.float64), np.ones((len(pts), 1), dtype=np.float64)], axis=1)
            prim_pts = ((hom @ local_to_prim)[:, :3] * meters_per_unit).astype(np.float32)
        except Exception:
            prim_pts = (pts[:, :3] * meters_per_unit).astype(np.float32)

        # Skip meshes with extreme extents (outlier / broken transform), > 100 m
        ext = prim_pts.max(axis=0) - prim_pts.min(axis=0)
        if np.any(ext > 100.0):
            continue

        # Triangulate faces
        tris: list[int] = []
        pos = 0
        for count in cnts:
            verts = idx[pos : pos + int(count)]
            for j in range(1, int(count) - 1):
                tris += [int(verts[0]), int(verts[j]), int(verts[j + 1])]
            pos += int(count)
        if not tris:
            continue

        tri_arr = np.asarray(tris, dtype=np.int32).reshape(-1, 3) + vertex_offset
        all_verts.append(prim_pts)
        all_tris.append(tri_arr)
        vertex_offset += len(prim_pts)

    if not all_verts:
        return None

    vertices = np.vstack(all_verts).astype(np.float32)
    triangles = np.vstack(all_tris).astype(np.int32)

    # Decimate: keep first N triangles (preserves connectivity near the base mesh)
    if len(triangles) > max_triangles:
        triangles = triangles[:max_triangles]
        used = np.unique(triangles)
        remap = np.zeros(len(vertices), dtype=np.int32)
        remap[used] = np.arange(len(used), dtype=np.int32)
        vertices = vertices[used]
        triangles = remap[triangles]

    # Center at origin
    center = (vertices.min(axis=0) + vertices.max(axis=0)) * 0.5
    vertices -= center

    return {
        "source_path": source_path,
        "vertices": vertices.flatten().tolist(),
        "indices": triangles.flatten().tolist(),
        "center_offset": center.tolist(),
        "vertex_count": int(len(vertices)),
        "triangle_count": int(len(triangles)),
    }
