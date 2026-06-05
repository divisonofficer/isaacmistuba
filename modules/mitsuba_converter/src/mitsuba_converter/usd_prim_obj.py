"""Per-prim USD → OBJ extraction for the OpticalNav editor render pipeline.

The render daemon's ``_proxy_box_xml_element`` used to emit cube proxies for
every authoring object. This module produces a small OBJ for a single USD prim
(and its mesh descendants) so the Mitsuba scene can reference the real geometry
instead. Vertices are written in prim-local meters with the bbox bottom shifted
to ``y=0`` so the renderer can place the object on the floor with a simple
translate.

Writer version 2 adds UV (``vt``) and normal (``vn``) output when the source
USD mesh has ``primvars:st`` and ``normals``; this lets the Mitsuba ``obj``
loader sample basecolor / normal textures bound on the USD material.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .usd_export_obj import _triangulate

OBJ_WRITER_VERSION = 2


@dataclass
class PrimMeshStats:
    vertex_count: int
    triangle_count: int
    mesh_prim_count: int
    bbox_min: list[float]
    bbox_max: list[float]
    bbox_size: list[float]
    bottom_shift_y: float  # how much we subtracted from y to put min.y at 0
    has_uv: bool = False
    has_normal: bool = False
    writer_version: int = OBJ_WRITER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "vertex_count": int(self.vertex_count),
            "triangle_count": int(self.triangle_count),
            "mesh_prim_count": int(self.mesh_prim_count),
            "bbox": {
                "min": self.bbox_min,
                "max": self.bbox_max,
                "size": self.bbox_size,
            },
            "bottom_shift_y": float(self.bottom_shift_y),
            "has_uv": bool(self.has_uv),
            "has_normal": bool(self.has_normal),
            "writer_version": int(self.writer_version),
        }


def _stage_meters_per_unit(stage: Any) -> float:
    try:
        from pxr import UsdGeom  # type: ignore

        v = float(UsdGeom.GetStageMetersPerUnit(stage))
        if 1e-6 < v < 1e3:
            return v
    except Exception:
        pass
    return 1.0


def _triangulate_with_corners(counts: list[int], indices: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """Fan triangulation preserving corner ids (face-vertex stream offsets)."""
    tris_v: list[list[int]] = []
    tris_c: list[list[int]] = []
    cursor = 0
    for c in counts:
        face_v = indices[cursor:cursor + c]
        face_c = list(range(cursor, cursor + c))
        cursor += c
        if c < 3:
            continue
        v0 = face_v[0]
        c0 = face_c[0]
        for k in range(1, c - 1):
            tris_v.append([v0, face_v[k], face_v[k + 1]])
            tris_c.append([c0, face_c[k], face_c[k + 1]])
    if not tris_v:
        return np.zeros((0, 3), dtype=np.int64), np.zeros((0, 3), dtype=np.int64)
    return np.asarray(tris_v, dtype=np.int64), np.asarray(tris_c, dtype=np.int64)


def _read_uvs(mesh_schema: Any, raw_idx: list[int]) -> tuple[np.ndarray | None, str]:
    """Return (uv_array, mode) where mode is 'vertex' / 'corner' / 'none'.

    'vertex' → 1 UV per point; 'corner' → 1 UV per face-vertex stream entry.
    """
    try:
        from pxr import UsdGeom  # type: ignore
    except Exception:
        return None, "none"
    try:
        st = UsdGeom.PrimvarsAPI(mesh_schema.GetPrim()).GetPrimvar("st")
    except Exception:
        return None, "none"
    if not st or not st.HasValue():
        return None, "none"
    st_val = st.Get()
    if st_val is None or len(st_val) == 0:
        return None, "none"
    try:
        interp = st.GetInterpolation()
    except Exception:
        interp = ""
    st_indices = None
    try:
        if st.IsIndexed():
            st_indices = st.GetIndices()
    except Exception:
        st_indices = None

    def _pair(i: int) -> tuple[float, float]:
        t = st_val[i]
        return float(t[0]), float(t[1])

    if interp == "vertex":
        try:
            arr = np.asarray([_pair(i) for i in range(len(st_val))], dtype=np.float32)
            return arr, "vertex"
        except Exception:
            return None, "none"
    # Treat anything else as faceVarying-ish.
    corner_count = len(raw_idx)
    try:
        if st_indices is not None and len(st_indices) == corner_count:
            arr = np.asarray([_pair(int(j)) for j in st_indices], dtype=np.float32)
            return arr, "corner"
        if len(st_val) == corner_count:
            arr = np.asarray([_pair(i) for i in range(corner_count)], dtype=np.float32)
            return arr, "corner"
    except Exception:
        pass
    return None, "none"


def _read_normals(mesh_schema: Any, transform_dir: Any) -> np.ndarray | None:
    """Per-point normals in world space (prim-local rotation already applied)."""
    try:
        n_attr = mesh_schema.GetNormalsAttr()
    except Exception:
        return None
    if not n_attr or not n_attr.HasValue():
        return None
    n_val = n_attr.Get()
    if n_val is None or len(n_val) == 0:
        return None
    try:
        normals = np.asarray([transform_dir((n[0], n[1], n[2])) for n in n_val], dtype=np.float64)
    except Exception:
        return None
    norms = np.linalg.norm(normals, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normals = normals / norms
    # Replace any non-finite vector with +Y so mitsuba's obj loader doesn't reject the file.
    bad = ~np.isfinite(normals).all(axis=1)
    if bad.any():
        normals[bad] = np.asarray((0.0, 1.0, 0.0), dtype=np.float64)
    return normals.astype(np.float32)


def extract_prim_mesh_to_obj(
    usd_path: str | Path,
    prim_path: str,
    out_obj_path: str | Path,
    *,
    max_mesh_prims: int = 256,
    center_bottom_at_origin: bool = True,
    stage: Any | None = None,
) -> PrimMeshStats | None:
    """Extract a prim's mesh descendants into a triangulated OBJ with UV/normals.

    Returns stats on success, ``None`` if the prim has no usable mesh.

    Coordinate convention: vertices are in prim-local space (the prim's own
    world transform is undone), scaled by ``metersPerUnit`` so values are
    metres. When ``center_bottom_at_origin`` is True (default) the global
    bbox is shifted so ``min.y == 0`` — this lets ``base_height_m`` in the
    authoring map double as the floor-anchored object height.
    """
    from pxr import Usd, UsdGeom  # type: ignore

    own_stage = False
    if stage is None:
        stage = Usd.Stage.Open(str(usd_path))
        if stage is None:
            return None
        own_stage = True

    try:
        prim = stage.GetPrimAtPath(prim_path)
        if not prim or not prim.IsValid():
            return None

        meters_per_unit = _stage_meters_per_unit(stage)
        xform_cache = UsdGeom.XformCache(Usd.TimeCode.Default())

        try:
            prim_world = np.asarray(xform_cache.GetLocalToWorldTransform(prim), dtype=np.float64).reshape(4, 4)
            prim_world_inv = np.linalg.inv(prim_world)
        except Exception:
            prim_world_inv = np.eye(4, dtype=np.float64)

        mesh_prims: list[Any] = []
        if prim.IsA(UsdGeom.Mesh):
            mesh_prims.append(prim)
        else:
            for child in Usd.PrimRange(prim):
                if child.IsA(UsdGeom.Mesh):
                    mesh_prims.append(child)
                if len(mesh_prims) >= max_mesh_prims:
                    break

        if not mesh_prims:
            return None

        all_v: list[np.ndarray] = []
        all_tris: list[np.ndarray] = []
        all_uvs: list[np.ndarray] = []           # one row per UV index emitted (vertex- or corner-keyed)
        all_normals: list[np.ndarray] = []        # per-vertex normals (one row per emitted vertex)
        # Per-mesh offsets and modes:
        v_offsets: list[int] = []
        uv_offsets: list[int] = []
        uv_modes: list[str] = []                  # "vertex" | "corner" | "none"
        corner_arrays: list[np.ndarray] = []      # per-mesh tris_c when uv_mode == "corner"
        normal_present: list[bool] = []
        vertex_offset = 0
        uv_offset = 0
        mesh_used = 0

        any_uv = False
        any_normal = False

        for mp in mesh_prims:
            mesh_schema = UsdGeom.Mesh(mp)
            raw_pts = mesh_schema.GetPointsAttr().Get()
            raw_idx = mesh_schema.GetFaceVertexIndicesAttr().Get()
            raw_cnts = mesh_schema.GetFaceVertexCountsAttr().Get()
            if raw_pts is None or raw_idx is None or raw_cnts is None:
                continue
            if len(raw_pts) == 0 or len(raw_idx) == 0:
                continue

            try:
                local_to_world = np.asarray(
                    xform_cache.GetLocalToWorldTransform(mp), dtype=np.float64
                ).reshape(4, 4)
            except Exception:
                local_to_world = np.eye(4, dtype=np.float64)

            full = prim_world_inv @ local_to_world
            pts = np.asarray(raw_pts, dtype=np.float64)
            hom = np.concatenate([pts, np.ones((pts.shape[0], 1), dtype=np.float64)], axis=1)
            world_pts = hom @ full.T
            local_pts = (world_pts[:, :3]) * meters_per_unit

            counts_list = list(raw_cnts)
            idx_list = list(raw_idx)
            tris_v, tris_c = _triangulate_with_corners(counts_list, idx_list)
            if tris_v.size == 0:
                continue

            # UVs
            uv_arr, uv_mode = _read_uvs(mesh_schema, idx_list)

            # Normals — transform direction using prim-local rotation (full[:3,:3])
            rot = full[:3, :3]

            def _tdir(n: tuple[float, float, float]) -> tuple[float, float, float]:
                v = rot @ np.asarray(n, dtype=np.float64)
                return float(v[0]), float(v[1]), float(v[2])

            normals = _read_normals(mesh_schema, _tdir)

            all_v.append(local_pts.astype(np.float32))
            all_tris.append(tris_v + vertex_offset)
            v_offsets.append(vertex_offset)
            if uv_arr is not None and uv_mode != "none":
                all_uvs.append(uv_arr)
                uv_modes.append(uv_mode)
                uv_offsets.append(uv_offset)
                corner_arrays.append(tris_c if uv_mode == "corner" else np.zeros((0, 3), dtype=np.int64))
                uv_offset += uv_arr.shape[0]
                any_uv = True
            else:
                uv_modes.append("none")
                uv_offsets.append(uv_offset)
                corner_arrays.append(np.zeros((0, 3), dtype=np.int64))

            if normals is not None and normals.shape[0] == local_pts.shape[0]:
                all_normals.append(normals)
                normal_present.append(True)
                any_normal = True
            else:
                all_normals.append(np.zeros((local_pts.shape[0], 3), dtype=np.float32))
                normal_present.append(False)

            vertex_offset += local_pts.shape[0]
            mesh_used += 1

        if vertex_offset == 0 or not all_tris:
            return None

        verts = np.concatenate(all_v, axis=0)

        bbox_min = verts.min(axis=0)
        bbox_max = verts.max(axis=0)

        bottom_shift = 0.0
        if center_bottom_at_origin:
            bottom_shift = float(bbox_min[1])
            verts[:, 1] = verts[:, 1] - bottom_shift
            bbox_min[1] = 0.0
            bbox_max[1] = bbox_max[1] - bottom_shift

        # If any mesh contributed UV or normals, we emit them for *all* meshes —
        # missing UVs become (0,0); missing normals become +Y. This keeps face
        # lines uniform across the file.
        write_uv = any_uv
        write_normal = any_normal

        out_path = Path(out_obj_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        total_tris = sum(t.shape[0] for t in all_tris)
        with out_path.open("w", encoding="utf-8") as f:
            f.write(f"# usd_path: {usd_path}\n")
            f.write(f"# prim_path: {prim_path}\n")
            f.write(f"# writer_version: {OBJ_WRITER_VERSION}\n")
            f.write(f"# vertices: {verts.shape[0]}\n")
            f.write(f"# triangles: {total_tris}\n")
            f.write(f"# has_uv: {int(write_uv)}\n")
            f.write(f"# has_normal: {int(write_normal)}\n")

            for x, y, z in verts:
                f.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")

            if write_uv:
                for uvs in all_uvs:
                    for u, vv in uvs:
                        f.write(f"vt {u:.6f} {vv:.6f}\n")
                if uv_offset == 0:
                    # All meshes had no UV but some flag tripped — emit one placeholder.
                    f.write("vt 0.000000 0.000000\n")

            if write_normal:
                for normals in all_normals:
                    for nx, ny, nz in normals:
                        f.write(f"vn {nx:.6f} {ny:.6f} {nz:.6f}\n")

            # Faces. Vertex indices are already vertex_offset-shifted in all_tris.
            for mesh_i, tris in enumerate(all_tris):
                v_off = v_offsets[mesh_i]  # absolute vertex offset for normal indices (same as position)
                uv_mode = uv_modes[mesh_i]
                uv_off = uv_offsets[mesh_i]
                corners = corner_arrays[mesh_i]
                for i, (a, b, c) in enumerate(tris):
                    va = int(a) + 1
                    vb = int(b) + 1
                    vc = int(c) + 1
                    if write_uv and write_normal:
                        if uv_mode == "vertex":
                            ta = int(a - v_off) + 1 + uv_off
                            tb = int(b - v_off) + 1 + uv_off
                            tc = int(c - v_off) + 1 + uv_off
                        elif uv_mode == "corner":
                            ca, cb, cc = corners[i]
                            ta = int(ca) + 1 + uv_off
                            tb = int(cb) + 1 + uv_off
                            tc = int(cc) + 1 + uv_off
                        else:
                            ta = tb = tc = 1
                        f.write(f"f {va}/{ta}/{va} {vb}/{tb}/{vb} {vc}/{tc}/{vc}\n")
                    elif write_uv:
                        if uv_mode == "vertex":
                            ta = int(a - v_off) + 1 + uv_off
                            tb = int(b - v_off) + 1 + uv_off
                            tc = int(c - v_off) + 1 + uv_off
                        elif uv_mode == "corner":
                            ca, cb, cc = corners[i]
                            ta = int(ca) + 1 + uv_off
                            tb = int(cb) + 1 + uv_off
                            tc = int(cc) + 1 + uv_off
                        else:
                            ta = tb = tc = 1
                        f.write(f"f {va}/{ta} {vb}/{tb} {vc}/{tc}\n")
                    elif write_normal:
                        f.write(f"f {va}//{va} {vb}//{vb} {vc}//{vc}\n")
                    else:
                        f.write(f"f {va} {vb} {vc}\n")

        return PrimMeshStats(
            vertex_count=int(verts.shape[0]),
            triangle_count=int(total_tris),
            mesh_prim_count=int(mesh_used),
            bbox_min=[float(bbox_min[0]), float(bbox_min[1]), float(bbox_min[2])],
            bbox_max=[float(bbox_max[0]), float(bbox_max[1]), float(bbox_max[2])],
            bbox_size=[
                float(bbox_max[0] - bbox_min[0]),
                float(bbox_max[1] - bbox_min[1]),
                float(bbox_max[2] - bbox_min[2]),
            ],
            bottom_shift_y=float(bottom_shift),
            has_uv=bool(write_uv),
            has_normal=bool(write_normal),
            writer_version=OBJ_WRITER_VERSION,
        )
    finally:
        if own_stage:
            del stage
