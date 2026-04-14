from __future__ import annotations

from pathlib import Path
from typing import List
import numpy as np


def _triangulate(counts: List[int], indices: List[int]) -> np.ndarray:
    tris = []
    cursor = 0
    for c in counts:
        face = indices[cursor:cursor + c]
        cursor += c
        if c < 3:
            continue
        v0 = face[0]
        for k in range(1, c - 1):
            tris.append([v0, face[k], face[k + 1]])
    return np.asarray(tris, dtype=np.int64)


def export_roots_to_obj(
    *,
    usd_path: str,
    root_prims: List[str],
    out_obj: str,
    max_meshes: int = 400,
) -> dict:
    """Export meshes under multiple root prims to a single OBJ.

    MVP:
    - triangulates faces (fan)
    - applies world transform per-prim
    - ignores materials/uvs/normals
    """
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.Open(usd_path)
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
    out_obj_p.parent.mkdir(parents=True, exist_ok=True)

    v_offset = 0
    mesh_written = 0
    total_tris = 0

    with out_obj_p.open("w", encoding="utf-8") as f:
        f.write(f"# USD export: {usd_path}\n")
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

                xf = xcache.GetLocalToWorldTransform(prim)
                v = np.asarray([(p[0], p[1], p[2], 1.0) for p in pts], dtype=np.float64)
                M = np.asarray(xf, dtype=np.float64)
                v_w = (v @ M.T)[:, :3]

                tris = _triangulate(list(counts), list(idx))
                if tris.size == 0:
                    continue

                f.write(f"\no {prim.GetName()}\n")
                for x, y, z in v_w:
                    f.write(f"v {x} {y} {z}\n")

                for a, b, c in tris:
                    f.write(f"f {int(a) + 1 + v_offset} {int(b) + 1 + v_offset} {int(c) + 1 + v_offset}\n")

                v_offset += v_w.shape[0]
                mesh_written += 1
                total_tris += tris.shape[0]

                if mesh_written >= max_meshes:
                    return {
                        "meshes": mesh_written,
                        "tris": int(total_tris),
                        "out_obj": str(out_obj_p),
                        "truncated": True,
                    }

    return {"meshes": mesh_written, "tris": int(total_tris), "out_obj": str(out_obj_p), "truncated": False}


if __name__ == "__main__":
    import argparse, json

    p = argparse.ArgumentParser()
    p.add_argument("--usd", required=True)
    p.add_argument("--root-prim", action="append", required=True, help="repeatable")
    p.add_argument("--out-obj", required=True)
    p.add_argument("--max-meshes", type=int, default=400)
    args = p.parse_args()

    report = export_roots_to_obj(
        usd_path=args.usd,
        root_prims=args.root_prim,
        out_obj=args.out_obj,
        max_meshes=args.max_meshes,
    )
    print(json.dumps(report, indent=2))
