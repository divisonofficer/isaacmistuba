"""Graphic patchwork tile floor (S34 high-ceiling LP cafe ref: black / red / white / mustard square ceramic tiles laid in stepped, pixel-like shapes). Hooked from kit_lighting after the carpet floor,
only when ROOM_FLOOR_PATCHWORK=1.

    from patchwork_floor import apply; stats["patchwork_floor"] = apply(stats)

Env: ROOM_PATCHWORK_ROOMS=break-room   room-name prefixes that get it (empty = every floor)   ROOM_PATCHWORK_TILE=0.3 tile edge in metres   ROOM_PATCHWORK_ROUGH=0.25 roughness (glazed ceramic)
The pattern is a 48 x 48 tile field (14.4 m at 0.3 m) baked once to data/venue_refs/tile_cache/patchwork_<hash>.png (32 px per tile, a 1 px grout line) and mapped in WORLD metres (Geometry Position),
so it is continuous across rooms and needs no UVs. Floor materials are copied and replaced as in carpet_floor.py. The field: black ground with a few big diagonal stepped bands (each a white band edged
red, or a mustard band edged white), like the reference's stair-stepped shapes.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import bpy

CACHE = Path("/jarvis/project/robomituba/data/venue_refs/tile_cache")
N, PX = 48, 32
COL = {"k": (22, 22, 24), "r": (205, 52, 30), "w": (236, 234, 228), "y": (226, 176, 48)}


def _field(seed):
    import random
    rng = random.Random(seed)
    g = [["k"] * N for _ in range(N)]
    for _ in range(7):                                                   # stepped diagonal bands
        cx, cy = rng.uniform(0, N), rng.uniform(0, N)
        ang = rng.choice((1, -1)) * rng.uniform(0.5, 1.0)               # slope of the band's axis
        half = rng.uniform(1.6, 3.2); length = rng.uniform(10, 22)
        main, edge = rng.choice((("r", "w"), ("w", "r"), ("r", "w"), ("y", "w"), ("r", "y"), ("w", "y")))
        for y in range(N):
            for x in range(N):
                dx, dy = x - cx, y - cy
                along = (dx + dy * ang) / (1 + abs(ang))                 # position along the band
                across = (dy - dx * ang) / (1 + abs(ang))                # distance from its axis
                if abs(along) < length / 2 and abs(across) < half + 1.2:
                    g[y][x] = main if abs(across) < half else edge
    return g


def _bake(tile):
    seed = 7
    key = hashlib.md5(repr((seed, N, PX)).encode()).hexdigest()[:10]
    out = CACHE / f"patchwork_{key}.png"
    size_m = tile * N
    if out.exists():
        return out, size_m
    import numpy as np
    from PIL import Image
    CACHE.mkdir(parents=True, exist_ok=True)
    g = _field(seed)
    img = np.zeros((N * PX, N * PX, 3), dtype=np.uint8)
    for y in range(N):
        for x in range(N):
            c = np.array(COL[g[y][x]], dtype=np.float64)
            blk = np.ones((PX, PX, 3)) * c
            blk[0, :] *= 0.55; blk[:, 0] *= 0.55                         # a 1 px grout line
            img[y * PX:(y + 1) * PX, x * PX:(x + 1) * PX] = blk.astype(np.uint8)
    Image.fromarray(img, "RGB").save(out)
    return out, size_m


def _mat(mat, img, size_m, rough):
    nt = mat.node_tree; N_, Lk = nt.nodes, nt.links
    b = next((n for n in N_ if n.type == "BSDF_PRINCIPLED"), None)
    if mat.get("patchwork"):
        return False
    if b is None:
        N_.clear(); b = N_.new("ShaderNodeBsdfPrincipled"); out = N_.new("ShaderNodeOutputMaterial"); Lk.new(b.outputs["BSDF"], out.inputs["Surface"])
    for l in list(b.inputs["Base Color"].links) + list(b.inputs["Roughness"].links):
        Lk.remove(l)
    geo = N_.new("ShaderNodeNewGeometry"); mp = N_.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (1.0 / size_m, 1.0 / size_m, 1.0)
    tx = N_.new("ShaderNodeTexImage"); tx.image = img; tx.interpolation = "Closest"; tx.extension = "REPEAT"
    Lk.new(geo.outputs["Position"], mp.inputs["Vector"]); Lk.new(mp.outputs["Vector"], tx.inputs["Vector"]); Lk.new(tx.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = rough
    mat["patchwork"] = True
    return True


def apply(stats):
    if os.environ.get("ROOM_FLOOR_PATCHWORK") != "1":
        return 0
    tile = float(os.environ.get("ROOM_PATCHWORK_TILE") or 0.3)
    rough = float(os.environ.get("ROOM_PATCHWORK_ROUGH") or 0.25)
    png, size_m = _bake(tile)
    img = bpy.data.images.load(str(png), check_existing=True); img.colorspace_settings.name = "sRGB"
    only = tuple(x.strip() for x in (os.environ.get("ROOM_PATCHWORK_ROOMS") or "").split(",") if x.strip())
    cnt, copies = 0, {}
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.name.endswith(".floor") or (only and not o.name.startswith(only)):
            continue
        for sl in o.material_slots:
            m = sl.material
            if m is None or not m.use_nodes:
                continue
            if m.name not in copies:
                c = m.copy(); c.name = f"{m.name}.patchwork"; copies[m.name] = c if _mat(c, img, size_m, rough) else m
            sl.material = copies[m.name]; cnt += 1
    stats["patchwork_floor"] = {"slots": cnt}
    return cnt


if __name__ == "__main__":
    g = _field(7)
    import collections
    print(collections.Counter(c for row in g for c in row))
