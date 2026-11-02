"""Pale porcelain tile floor for chosen room types (P2 r14 review: kitchen / utility / balcony / baths had timber, the reference has pale porcelain tile). Hooked from kit_lighting after the carpet floor, only
when ROOM_FLOOR_TILE_ROOMS is set.

    from tile_floor import apply; stats["tile_floor"] = apply(stats)

Env:  ROOM_FLOOR_TILE_ROOMS=kitchen,utility,balcony,bathroom,restroom   room-name prefixes whose `.floor` gets the tile (other rooms keep their floor)
      ROOM_FLOOR_TILE_MAP=restroom:0.3,0.31,0.33@0.9;warehouse:0.55,0.55,0.54@3.0   a tile colour (and optional @edge in m) per room-name prefix (longest prefix wins; others: ROOM_FLOOR_TILE)
      ROOM_FLOOR_TILE=r,g,b            base colour, sRGB 0..1 (default 0.82,0.8,0.76 pale warm porcelain)     ROOM_TILE_SIZE=0.6   tile edge in metres
      ROOM_TILE_GROUT=0.003            grout width (m)     ROOM_TILE_VARY=0.04   per-tile tone variation     ROOM_TILE_ROUGH=0.25
Baked once into a 4096 px tileable image (period 4.8 m, a soft marble-like drift inside each tile, light-grey grout), cached in data/venue_refs/tile_cache, mapped in world metres like herringbone_floor.py.
"""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path

import bpy

CACHE = Path("/jarvis/project/robomituba/data/venue_refs/tile_cache")
PX = 4096


def _bake(base, tile, grout, vary):
    import numpy as np
    from PIL import Image
    n = max(2, int(round(4.8 / tile))); size_m = n * tile
    key = hashlib.md5(repr((tuple(round(b, 3) for b in base), round(tile, 3), round(grout, 4), round(vary, 3), PX)).encode()).hexdigest()[:12]
    out = CACHE / f"tl_{key}.png"
    if out.exists():
        return out, size_m
    CACHE.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(int(key[:8], 16))
    px = (np.arange(PX, dtype=np.float64) + 0.5) / PX * n
    u, v = np.meshgrid(px, px); c, r = np.floor(u).astype(np.int64), np.floor(v).astype(np.int64)
    fu, fv = u - c, v - r
    tone = (rng.random((n, n)) - 0.5) * 2 * vary; t = tone[c % n, r % n]
    # a soft marble-like drift: a few low-frequency sines with a random phase per tile
    ph = rng.random((n, n, 3)) * 6.283
    drift = (np.sin(fu * 3.1 + ph[c % n, r % n, 0]) * np.sin(fv * 2.3 + ph[c % n, r % n, 1]) + np.sin((fu + fv) * 4.0 + ph[c % n, r % n, 2]) * 0.5) * 0.015
    col = np.stack([base[0] * (1 + t) + drift, base[1] * (1 + t) + drift, base[2] * (1 + t) + drift * 0.8], axis=-1)
    edge = np.minimum(np.minimum(fu, 1 - fu), np.minimum(fv, 1 - fv)) * tile
    gw = np.clip((grout / 2.0 - edge) / 0.0008 + 0.5, 0.0, 1.0)[..., None] if grout > 0 else 0.0
    gc = np.array([min(1.0, b * 0.8) for b in base]) * 0.92
    col = col * (1 - gw) + gc * gw
    Image.fromarray((np.clip(col, 0, 1) * 255.0 + 0.5).astype(np.uint8), "RGB").save(out)
    return out, size_m


def _tile(mat, img, size_m, rough):
    nt = mat.node_tree; N, Lk = nt.nodes, nt.links
    b = next((x for x in N if x.type == "BSDF_PRINCIPLED"), None)
    if mat.get("tile_floor"):
        return False
    if b is None:
        N.clear(); b = N.new("ShaderNodeBsdfPrincipled"); o = N.new("ShaderNodeOutputMaterial"); Lk.new(b.outputs["BSDF"], o.inputs["Surface"])
    for l in list(b.inputs["Base Color"].links) + list(b.inputs["Roughness"].links):
        Lk.remove(l)
    geo = N.new("ShaderNodeNewGeometry"); mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (1.0 / size_m, 1.0 / size_m, 1.0)
    tx = N.new("ShaderNodeTexImage"); tx.image = img; tx.interpolation = "Smart"; tx.extension = "REPEAT"
    Lk.new(geo.outputs["Position"], mp.inputs["Vector"]); Lk.new(mp.outputs["Vector"], tx.inputs["Vector"]); Lk.new(tx.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = rough
    mat["tile_floor"] = True
    return True


def apply(stats):
    rooms = tuple(x.strip() for x in (os.environ.get("ROOM_FLOOR_TILE_ROOMS") or "").split(",") if x.strip())
    if not rooms:
        return 0
    base = tuple(float(v) for v in (os.environ.get("ROOM_FLOOR_TILE") or "0.82,0.8,0.76").split(","))
    # ROOM_FLOOR_TILE_MAP="restroom:0.3,0.31,0.33;kitchen:0.8,0.79,0.76": a tile colour per room-name prefix (longest prefix wins); rooms not matched take ROOM_FLOOR_TILE
    cmap = {}
    for part in (os.environ.get("ROOM_FLOOR_TILE_MAP") or "").split(";"):
        if ":" in part:
            k_, v_ = part.split(":", 1)
            v_, _, sz_ = v_.partition("@")                                       # "prefix:r,g,b@size": an optional per-prefix tile edge in metres (restroom 0.9, warehouse slabs 3.0)
            cmap[k_.strip()] = (tuple(float(x) for x in v_.split(",")), float(sz_) if sz_ else None)
    tile = float(os.environ.get("ROOM_TILE_SIZE") or 0.6); grout = float(os.environ.get("ROOM_TILE_GROUT") or 0.003)
    vary = float(os.environ.get("ROOM_TILE_VARY") or 0.04); rough = float(os.environ.get("ROOM_TILE_ROUGH") or 0.25)
    imgs = {}
    def img_for(col, tsz):
        if (col, tsz) not in imgs:
            png, size_m = _bake(col, tsz, grout if tsz < 1.5 else grout * 3, vary)
            im = bpy.data.images.load(str(png), check_existing=True); im.colorspace_settings.name = "sRGB"
            imgs[(col, tsz)] = (im, size_m)
        return imgs[(col, tsz)]
    cnt, copies = 0, {}
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.name.endswith(".floor") or not o.name.startswith(rooms):
            continue
        col, tsz = base, tile
        for k_ in sorted(cmap, key=len, reverse=True):
            if o.name.startswith(k_):
                col = cmap[k_][0]; tsz = cmap[k_][1] or tile; break
        img, size_m = img_for(col, tsz)
        for sl in o.material_slots:
            m = sl.material
            if m is None or not m.use_nodes:
                continue
            key = (m.name, col, tsz)
            if key not in copies:
                c = m.copy(); c.name = f"{m.name}.tile{'' if (col == base and tsz == tile) else '.' + '_'.join(str(int(v * 100)) for v in col) + '_' + str(int(tsz * 10))}"; copies[key] = c if _tile(c, img, size_m, rough) else m
            sl.material = copies[key]; cnt += 1
    stats["tile_floor"] = {"slots": cnt, "rooms": list(rooms), "colours": len(imgs)}
    return cnt
