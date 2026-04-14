from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import re
import numpy as np


def _triangulate_with_corners(counts: List[int], indices: List[int]) -> tuple[np.ndarray, np.ndarray]:
    """Fan triangulation while preserving *corner ids* (face-vertex order).

    Returns:
      - tris_v: (T,3) vertex indices
      - tris_c: (T,3) corner indices into the flattened face-vertex stream
    """
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
    return np.asarray(tris_v, dtype=np.int64), np.asarray(tris_c, dtype=np.int64)


def _safe_name(s: str) -> str:
    s = s.strip('/').replace('/', '_')
    s = re.sub(r'[^A-Za-z0-9_\-]+', '_', s)
    s = re.sub(r'_+', '_', s)
    if not s:
        return 'mat'
    return s


@dataclass
class ExportStats:
    meshes: int
    tris: int
    materials: int
    truncated: bool


def export_roots_to_obj_mtl(
    *,
    usd_path: str,
    root_prims: List[str],
    out_obj: str,
    out_mtl: str,
    max_meshes: int = 500,
    smooth_normals: bool = True,
) -> Tuple[ExportStats, Dict]:
    """Export meshes under multiple root prims to OBJ+MTL.

    MVP features:
    - positions (v)
    - UVs (vt) if primvars:st exists
    - normals (vn): uses USD normals if present, else computes smooth vertex normals
    - face groups by bound material (usemtl)

    Materials:
    - Writes a minimal MTL mapping baseColor textures when available via USDPreviewSurface/UsdUVTexture.
    """
    from pxr import Usd, UsdGeom, UsdShade

    usd_p = Path(usd_path)
    stage = Usd.Stage.Open(str(usd_p))
    if stage is None:
        raise RuntimeError(f"Failed to open USD: {usd_path}")

    roots = []
    for rp in root_prims:
        prim = stage.GetPrimAtPath(rp)
        if not prim:
            raise RuntimeError(f"Prim not found: {rp}")
        roots.append(prim)

    xcache = UsdGeom.XformCache()

    out_obj_p = Path(out_obj)
    out_mtl_p = Path(out_mtl)
    out_obj_p.parent.mkdir(parents=True, exist_ok=True)
    out_mtl_p.parent.mkdir(parents=True, exist_ok=True)

    # --- Material extraction helpers ---
    mat_info: Dict[str, Dict] = {}

    def resolve_asset(asset) -> Optional[str]:
        if not asset:
            return None
        s = str(asset).strip('@')
        return str((usd_p.parent / s).resolve())

    def unwrap(x):
        while isinstance(x, (tuple, list)) and len(x) > 0:
            x = x[0]
        return x

    def as_shader(conn):
        conn = unwrap(conn)
        return UsdShade.Shader(conn.GetPrim())

    def extract_basecolor_texture(material: UsdShade.Material) -> Optional[str]:
        # Find connected UsdPreviewSurface then its diffuseColor -> UsdUVTexture.file
        surf_out = material.GetSurfaceOutput()
        if not surf_out:
            return None
        src = surf_out.GetConnectedSource()
        if not src:
            return None
        conn, _, _ = src
        shader = as_shader(conn)
        inp = shader.GetInput('diffuseColor')
        if not inp:
            return None
        c = inp.GetConnectedSource()
        if not c:
            return None
        conn2, _, _ = c
        sh2 = as_shader(conn2)
        sid = sh2.GetIdAttr().Get() or ''
        if 'UVTexture' not in sid and 'UsdUVTexture' not in sid:
            return None
        file_in = sh2.GetInput('file')
        asset = file_in.Get() if file_in else None
        return resolve_asset(asset)

    def get_bound_material_name(prim) -> str:
        m = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
        m = unwrap(m)
        if not m:
            return 'mat_default'
        mp = str(m.GetPath())
        if mp not in mat_info:
            tex = extract_basecolor_texture(m)
            mat_name = _safe_name(mp)
            mat_info[mp] = {
                'usdMaterialPath': mp,
                'mtlName': mat_name,
                'baseColorTex': tex,
            }
        return mat_info[mp]['mtlName']

    # --- Normal computation ---
    def compute_smooth_normals(v: np.ndarray, tris: np.ndarray) -> np.ndarray:
        # v: (N,3), tris: (T,3)
        n = np.zeros_like(v, dtype=np.float64)
        v0 = v[tris[:, 0]]
        v1 = v[tris[:, 1]]
        v2 = v[tris[:, 2]]
        fn = np.cross(v1 - v0, v2 - v0)
        # accumulate
        for i in range(3):
            np.add.at(n, tris[:, i], fn)
        # normalize
        norm = np.linalg.norm(n, axis=1, keepdims=True)
        norm[norm == 0] = 1
        return (n / norm).astype(np.float64)

    v_offset = 0
    vt_offset = 0
    vn_offset = 0

    mesh_written = 0
    total_tris = 0

    with out_obj_p.open('w', encoding='utf-8') as f:
        f.write(f"# USD export: {usd_path}\n")
        f.write(f"mtllib {out_mtl_p.name}\n")
        for rp in root_prims:
            f.write(f"# root_prim: {rp}\n")

        def iter_meshes(root_prim):
            for prim in Usd.PrimRange(root_prim):
                if prim.IsA(UsdGeom.Mesh):
                    yield prim

        for root in roots:
            for prim in iter_meshes(root):
                mesh = UsdGeom.Mesh(prim)

                pts = mesh.GetPointsAttr().Get() or []
                counts = mesh.GetFaceVertexCountsAttr().Get() or []
                idx = mesh.GetFaceVertexIndicesAttr().Get() or []
                if not pts or not counts or not idx:
                    continue

                # Transform positions to world
                xf = xcache.GetLocalToWorldTransform(prim)
                v = np.asarray([(p[0], p[1], p[2], 1.0) for p in pts], dtype=np.float64)
                M = np.asarray(xf, dtype=np.float64)
                v_w = (v @ M.T)[:, :3]

                tris_v, tris_c = _triangulate_with_corners(list(counts), list(idx))
                if tris_v.size == 0:
                    continue

                # UVs (vt)
                # Support both vertex and faceVarying primvars:st.
                # - vertex: 1 UV per point (index by vertex id)
                # - faceVarying: 1 UV per corner in face-vertex stream (index by corner id)
                uvs_vertex = None
                uvs_corner = None

                st = UsdGeom.PrimvarsAPI(prim).GetPrimvar('st')
                if st and st.HasValue():
                    st_val = st.Get()
                    st_indices = st.GetIndices() if st.IsIndexed() else None
                    interp = st.GetInterpolation()
                    corner_count = len(idx)

                    def get_uv(i: int):
                        t = st_val[i]
                        return float(t[0]), float(t[1])

                    if st_val is not None:
                        if interp == 'vertex' and len(st_val) == len(pts):
                            uvs_vertex = np.asarray([get_uv(i) for i in range(len(st_val))], dtype=np.float64)
                        else:
                            # Treat as faceVarying-like: build per-corner UVs
                            if st_indices is not None and len(st_indices) == corner_count:
                                uvs_corner = np.asarray([get_uv(int(j)) for j in st_indices], dtype=np.float64)
                            elif len(st_val) == corner_count:
                                uvs_corner = np.asarray([get_uv(i) for i in range(corner_count)], dtype=np.float64)
                            # else: unsupported layout -> leave None

                # Normals (vn)
                normals = None
                n_attr = mesh.GetNormalsAttr()
                if n_attr and n_attr.HasValue():
                    n_val = n_attr.Get()
                    if n_val is not None and len(n_val) == len(pts):
                        # transform dir
                        # Use xf without translation
                        def tdir(vec):
                            return np.asarray(xcache.GetLocalToWorldTransform(prim).TransformDir(vec), dtype=np.float64)
                        normals = np.asarray([tdir((n[0], n[1], n[2])) for n in n_val], dtype=np.float64)
                        # normalize
                        nn = np.linalg.norm(normals, axis=1, keepdims=True)
                        nn[nn == 0] = 1
                        normals = normals / nn

                if normals is None and smooth_normals:
                    normals = compute_smooth_normals(v_w, tris_v)

                mtl = get_bound_material_name(prim)

                f.write(f"\no {prim.GetName()}\n")
                f.write(f"usemtl {mtl}\n")

                # write vertices
                for x, y, z in v_w:
                    f.write(f"v {x} {y} {z}\n")

                # write UVs
                if uvs_vertex is not None:
                    for u, vv in uvs_vertex:
                        f.write(f"vt {u} {vv}\n")
                elif uvs_corner is not None:
                    for u, vv in uvs_corner:
                        f.write(f"vt {u} {vv}\n")

                # write normals
                if normals is not None:
                    for nx, ny, nz in normals:
                        f.write(f"vn {nx} {ny} {nz}\n")

                # write faces
                for (a, b, c), (ca, cb, cc) in zip(tris_v, tris_c):
                    va, vb, vc = int(a) + 1 + v_offset, int(b) + 1 + v_offset, int(c) + 1 + v_offset

                    has_vt = (uvs_vertex is not None) or (uvs_corner is not None)
                    if has_vt and normals is not None:
                        if uvs_vertex is not None:
                            ta, tb, tc = int(a) + 1 + vt_offset, int(b) + 1 + vt_offset, int(c) + 1 + vt_offset
                        else:
                            ta, tb, tc = int(ca) + 1 + vt_offset, int(cb) + 1 + vt_offset, int(cc) + 1 + vt_offset
                        na, nb, nc = int(a) + 1 + vn_offset, int(b) + 1 + vn_offset, int(c) + 1 + vn_offset
                        f.write(f"f {va}/{ta}/{na} {vb}/{tb}/{nb} {vc}/{tc}/{nc}\n")
                    elif has_vt:
                        if uvs_vertex is not None:
                            ta, tb, tc = int(a) + 1 + vt_offset, int(b) + 1 + vt_offset, int(c) + 1 + vt_offset
                        else:
                            ta, tb, tc = int(ca) + 1 + vt_offset, int(cb) + 1 + vt_offset, int(cc) + 1 + vt_offset
                        f.write(f"f {va}/{ta} {vb}/{tb} {vc}/{tc}\n")
                    elif normals is not None:
                        na, nb, nc = int(a) + 1 + vn_offset, int(b) + 1 + vn_offset, int(c) + 1 + vn_offset
                        f.write(f"f {va}//{na} {vb}//{nb} {vc}//{nc}\n")
                    else:
                        f.write(f"f {va} {vb} {vc}\n")

                v_offset += v_w.shape[0]
                if uvs_vertex is not None:
                    vt_offset += uvs_vertex.shape[0]
                elif uvs_corner is not None:
                    vt_offset += uvs_corner.shape[0]
                if normals is not None:
                    vn_offset += normals.shape[0]

                mesh_written += 1
                total_tris += tris_v.shape[0]

                if mesh_written >= max_meshes:
                    # stop early
                    stats = ExportStats(meshes=mesh_written, tris=int(total_tris), materials=len(mat_info), truncated=True)
                    _write_mtl(out_mtl_p, mat_info)
                    return stats, {'mat_info': mat_info}

    stats = ExportStats(meshes=mesh_written, tris=int(total_tris), materials=len(mat_info), truncated=False)
    _write_mtl(out_mtl_p, mat_info)
    return stats, {'mat_info': mat_info}


def _write_mtl(out_mtl_p: Path, mat_info: Dict[str, Dict]) -> None:
    # Minimal MTL with diffuse map
    lines = []
    lines.append('# Generated by usd_export_obj_mtl.py')
    for mp, mi in mat_info.items():
        lines.append(f"\nnewmtl {mi['mtlName']}")
        # default values
        lines.append('Kd 0.78 0.78 0.78')
        tex = mi.get('baseColorTex')
        if tex:
            lines.append(f"map_Kd {tex}")
    out_mtl_p.write_text('\n'.join(lines) + '\n', encoding='utf-8')


if __name__ == '__main__':
    import argparse, json

    p = argparse.ArgumentParser()
    p.add_argument('--usd', required=True)
    p.add_argument('--root-prim', action='append', required=True)
    p.add_argument('--out-obj', required=True)
    p.add_argument('--out-mtl', required=True)
    p.add_argument('--max-meshes', type=int, default=500)
    args = p.parse_args()

    stats, extra = export_roots_to_obj_mtl(
        usd_path=args.usd,
        root_prims=args.root_prim,
        out_obj=args.out_obj,
        out_mtl=args.out_mtl,
        max_meshes=args.max_meshes,
    )
    print(json.dumps({'stats': stats.__dict__, 'materials': list(extra['mat_info'].values())[:20]}, indent=2))
