#!/usr/bin/env python3
"""Is the writing actually visible from this camera?

Angle cannot answer it. Measured on 93 human verdicts: both the kept and the
excluded frames pile up at 0-30 and 150-180 degrees of incidence, because a
camera square on the BACK of a clock is square on. What separates them is which
surface the first thing in front of the lens belongs to, and that is a ray cast,
not a dot product.

One ray, camera to aim. If the nearest hit is the aim point itself the writing
is in view; if something intercepts first -- another object, a table edge, or
the far side of this same object -- it is not. The scene mesh is assembled in
world space from the manifest's instances, with the same settle correction the
poses use, so the geometry tested is the geometry rendered.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
import numpy as np
import trimesh

#: trimesh hands these GLBs back in their own glTF Y-up frame; the composer's
#: blender_matrix expects that frame. Verified against a raw TEXCOORD_0/vertex
#: accessor, not assumed.
YUP_TO_ZUP = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float)


def world_mesh(manifest: dict, boxes_by_src: dict | None = None):
    """Every instance of a scene, posed, as one mesh in world coordinates."""
    parts = []
    for inst in manifest.get("instances", []):
        glb = inst.get("source_glb")
        if not glb or not Path(glb).is_file():
            continue
        try:
            scene = trimesh.load(glb, force="scene", process=False)
        except Exception:
            continue
        M = np.asarray(inst["blender_matrix"], float)
        geoms = [g for g in scene.geometry.values() if hasattr(g, "vertices")]
        if not geoms:
            continue
        delta = np.zeros(3)
        box = (boxes_by_src or {}).get(inst.get("source_id"))
        if box is not None:
            lo, hi = np.asarray(scene.bounds[0]), np.asarray(scene.bounds[1])
            pred = M[:3, :3] @ (YUP_TO_ZUP @ ((lo + hi) / 2)) + M[:3, 3]
            delta = np.asarray(box["centre"], float) - pred
        for g in geoms:
            m = g.copy()
            v = np.asarray(m.vertices, float)
            m.vertices = (M[:3, :3] @ (YUP_TO_ZUP @ v.T)).T + M[:3, 3] + delta
            parts.append(m)
    if not parts:
        return None
    return trimesh.util.concatenate(parts)


def _ray_hits(mesh, origin, direction, eps=1e-9):
    """Distances along one ray to every triangle it crosses (Moller-Trumbore).

    Written out rather than calling mesh.ray: trimesh's pure-python engine needs
    rtree, which is not in this environment, and adding it would mean installing
    into an interpreter other sessions are training in. One ray against ~1e5
    triangles is a handful of numpy ops.
    """
    tri = np.asarray(mesh.triangles, float)
    v0, v1, v2 = tri[:, 0], tri[:, 1], tri[:, 2]
    e1, e2 = v1 - v0, v2 - v0
    h = np.cross(direction, e2)
    a = np.einsum("ij,ij->i", e1, h)
    ok = np.abs(a) > eps
    f = np.zeros_like(a)
    f[ok] = 1.0 / a[ok]
    s = origin - v0
    u = f * np.einsum("ij,ij->i", s, h)
    ok &= (u >= -1e-7) & (u <= 1 + 1e-7)
    q = np.cross(s, e1)
    v = f * (q @ direction)
    ok &= (v >= -1e-7) & (u + v <= 1 + 1e-7)
    t = f * np.einsum("ij,ij->i", e2, q)
    ok &= t > 1e-6
    return t[ok]


def visible(mesh, camera, aim, tol=0.01):
    """True when the first surface along camera->aim IS the aim point.

    `tol` is a surface tolerance, not a guess: the aim sits ON a triangle, so
    the nearest hit is that triangle at the aim's own distance. Anything
    materially nearer is between the lens and the writing.
    """
    camera = np.asarray(camera, float)
    aim = np.asarray(aim, float)
    d = aim - camera
    dist = float(np.linalg.norm(d))
    if dist < 1e-9:
        return None
    d = d / dist
    t = _ray_hits(mesh, camera, d)
    if t.size == 0:
        return {"visible": False, "first_hit_m": None, "aim_m": round(dist, 4),
                "reason": "no surface along the ray"}
    first = float(t.min())
    return {"visible": bool(first >= dist - tol), "first_hit_m": round(first, 4),
            "aim_m": round(dist, 4),
            "reason": "" if first >= dist - tol else f"blocked {dist - first:.3f} m short"}


def _self_check() -> None:
    # a quad at the origin facing +z, and a blocker between it and the camera
    panel = trimesh.Trimesh(vertices=[[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]],
                            faces=[[0, 1, 2], [0, 2, 3]], process=False)
    clear = visible(panel, [0, 0, 2], [0, 0, 0])
    assert clear["visible"], clear
    blocker = trimesh.Trimesh(vertices=[[-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]],
                              faces=[[0, 1, 2], [0, 2, 3]], process=False)
    both = trimesh.util.concatenate([panel, blocker])
    got = visible(both, [0, 0, 2], [0, 0, 0])
    assert not got["visible"] and got["first_hit_m"] < got["aim_m"], got
    # the case angle cannot see: a camera BEHIND the panel, square on. The panel
    # itself is the first hit, at the aim's distance, so this reads visible --
    # which is correct for a single plane and is why the corpus also needs the
    # aim to be on a face that carries the writing, not merely reachable.
    back = visible(panel, [0, 0, -2], [0, 0, 0])
    assert back["visible"], back
    # a box: aiming at the far wall from outside must be blocked by the near one
    box = trimesh.creation.box(extents=[1, 1, 1])
    got = visible(box, [0, 0, 3], [0, 0, -0.5])
    assert not got["visible"], got
    print("self-check ok")


if __name__ == "__main__":
    _self_check()
