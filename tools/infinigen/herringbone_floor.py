"""Herringbone plank floor (S13 review: the reference floor is a pale lilac herringbone tile, ours a plain white-grey one; user 2026-10-20). Hooked from kit_lighting after terrazzo_floor,
only when ROOM_FLOOR_HERRINGBONE is set.

    from herringbone_floor import apply; stats["herringbone_floor"] = apply(stats)

Env:  ROOM_FLOOR_HERRINGBONE=r,g,b   base colour, sRGB 0..1 (lilac 0.78,0.68,0.78; a parquet: 0.55,0.38,0.22)
      ROOM_HERRINGBONE_PLANK=0.12,0.6   plank width, length in metres (length / width is rounded to a whole number n >= 2)
      ROOM_HERRINGBONE_GROUT=0.003      grout line width in metres (light grey, a little lighter than the planks; 0 = none)
      ROOM_HERRINGBONE_VARY=0.07        per-plank tone variation (+- fraction)   ROOM_HERRINGBONE_ROUGH=0.3   roughness   ROOM_HERRINGBONE_ANGLE=0   rotation in degrees
The pattern is a classic V herringbone: with cells of one plank width, cell (c, r) lies on the diagonal d = c - r; diagonal bands of n cells alternate between planks lying along x (row r)
and planks lying along y (column c). It is baked into a 4096 px tileable image (period 4.8 m, one random tone per plank, a different seed per colour) cached in
data/venue_refs/herringbone_cache, and mapped in WORLD metres (Geometry Position), so it runs on through room boundaries and needs no UVs. Every room `.floor` material is copied and its
Base Color replaced; a floor shader that is not a Principled BSDF is replaced by one, like terrazzo_floor.
"""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path

import bpy

CACHE = Path("/jarvis/project/robomituba/data/venue_refs/herringbone_cache")
TILE_M = 4.8
PX = 4096


def _bake(base, wpl, lpl, grout, vary, straight=False):
    import numpy as np
    from PIL import Image
    n = max(2, round(lpl / wpl))
    key = hashlib.md5(repr((base, round(wpl, 4), n, round(grout, 4), round(vary, 3), PX, TILE_M) + (("straight",) if straight else ())).encode()).hexdigest()[:12]
    out = CACHE / f"hb_{key}.png"
    if out.exists():
        return out, n
    CACHE.mkdir(parents=True, exist_ok=True)
    cells = int(round(TILE_M / wpl))
    cells -= cells % (n if straight else 2 * n)                # a whole number of 2n-cell periods so the image tiles (n for straight planks)
    size_m = cells * wpl
    px = (np.arange(PX, dtype=np.float64) + 0.5) / PX * cells   # coordinates in plank widths
    u, v = np.meshgrid(px, px)                                  # u along x, v along y (image row 0 = v 0)
    c, r = np.floor(u).astype(np.int64), np.floor(v).astype(np.int64)
    if straight:                                                # ROOM_HERRINGBONE_STRAIGHT=1: long planks all along x, a random stagger per row (a plank floor, not herringbone)
        rh = np.mod(r * 2654435761 ^ int(key[:6], 16), 997) / 997.0
        uo = u + rh * n                                         # period: cells is a multiple of n, so the stagger tiles
        c0 = np.floor(uo / n) * n
        horiz = np.ones_like(c, dtype=bool); id_a = np.floor(uo / n).astype(np.int64); id_b = r
        lu = uo - c0; lv = v - r; plen = float(n); pw = 1.0
    else:
        d = c - r
        m = np.floor_divide(d, 2 * n); dm = d - 2 * n * m
        horiz = dm < n
        c0 = r + 2 * m * n                                          # horizontal plank: first column; row r
        r0 = c - 2 * m * n - 2 * n + 1                              # vertical plank: first (lowest) row; column c
        id_a = np.where(horiz, c0, c); id_b = np.where(horiz, r, r0)
        lu = np.where(horiz, u - c0, u - c); lv = np.where(horiz, v - r, v - r0)       # position inside the plank (plank widths)
        plen = np.where(horiz, n, 1.0); pw = np.where(horiz, 1.0, n)                     # extents along u / v
    edge = np.minimum(np.minimum(lu, plen - lu), np.minimum(lv, pw - lv)) * wpl      # metres to the nearest plank edge
    # one random tone per plank: a hash of (id_a mod period, id_b mod period, orientation) so the tile stays periodic
    ia = np.mod(id_a, cells); ib = np.mod(id_b, cells)
    h = (ia * 73856093) ^ (ib * 19349663) ^ (horiz.astype(np.int64) * 83492791) ^ int(key[:6], 16)
    rnd = (np.mod(h * 2654435761, 2 ** 32) / 2 ** 32)
    tone = 1.0 + (rnd - 0.5) * 2.0 * vary
    tint = (np.mod(h * 40503, 997) / 997.0 - 0.5) * 0.03        # a little hue wobble per plank
    col = np.stack([base[0] * tone + tint, base[1] * tone, base[2] * tone - tint], axis=-1)
    gc = np.array([min(1.0, b * 0.5 + 0.55) for b in base])    # grout: pale, close to the plank colour
    gw = np.clip((grout / 2.0 - edge) / 0.0008 + 0.5, 0.0, 1.0)[..., None] if grout > 0 else 0.0
    col = col * (1.0 - gw) + gc * gw
    Image.fromarray((np.clip(col, 0, 1) * 255.0 + 0.5).astype(np.uint8), "RGB").save(out)
    (CACHE / f"{out.stem}.json").write_text('{"size_m": %.4f}' % size_m)
    return out, n


def _size_m(png):
    import json
    try:
        return float(json.loads(png.with_suffix(".json").read_text())["size_m"])
    except Exception:                                                  # noqa: BLE001
        return TILE_M


def _herringbone(mat, img, size_m, rough, angle):
    nt = mat.node_tree; N, Lk = nt.nodes, nt.links
    b = next((n for n in N if n.type == "BSDF_PRINCIPLED"), None)
    if mat.get("herringbone"):
        return False
    if b is None:
        N.clear(); b = N.new("ShaderNodeBsdfPrincipled"); out = N.new("ShaderNodeOutputMaterial"); Lk.new(b.outputs["BSDF"], out.inputs["Surface"])
    for l in list(b.inputs["Base Color"].links) + list(b.inputs["Roughness"].links):
        Lk.remove(l)
    geo = N.new("ShaderNodeNewGeometry"); mp = N.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1.0 / size_m, 1.0 / size_m, 1.0); mp.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(angle))
    tx = N.new("ShaderNodeTexImage"); tx.image = img; tx.interpolation = "Smart"; tx.extension = "REPEAT"
    Lk.new(geo.outputs["Position"], mp.inputs["Vector"]); Lk.new(mp.outputs["Vector"], tx.inputs["Vector"]); Lk.new(tx.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = rough
    mat["herringbone"] = True
    return True


def apply(stats):
    raw = os.environ.get("ROOM_FLOOR_HERRINGBONE")
    if not raw:
        return 0
    base = tuple(float(v) for v in raw.split(","))
    wpl, lpl = (float(v) for v in (os.environ.get("ROOM_HERRINGBONE_PLANK") or "0.12,0.6").split(","))
    grout = float(os.environ.get("ROOM_HERRINGBONE_GROUT") or 0.003)
    vary = float(os.environ.get("ROOM_HERRINGBONE_VARY") or 0.07)
    rough = float(os.environ.get("ROOM_HERRINGBONE_ROUGH") or 0.3)
    angle = float(os.environ.get("ROOM_HERRINGBONE_ANGLE") or 0.0)
    straight = os.environ.get("ROOM_HERRINGBONE_STRAIGHT") == "1"
    only = tuple(x.strip() for x in (os.environ.get("ROOM_HERRINGBONE_ROOMS") or "").split(",") if x.strip())      # room-name prefixes that get the wood (office3: offices + meeting room; empty = every floor)
    png, n = _bake(base, wpl, lpl, grout, vary, straight)
    img = bpy.data.images.load(str(png), check_existing=True); img.colorspace_settings.name = "sRGB"
    size_m = _size_m(png)
    cnt, copies = 0, {}
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.name.endswith(".floor") or (only and not o.name.startswith(only)):
            continue
        for sl in o.material_slots:
            m = sl.material
            if m is None or not m.use_nodes:
                continue
            if m.name not in copies:
                c = m.copy(); c.name = m.name + ".hb"; copies[m.name] = c if _herringbone(c, img, size_m, rough, angle) else m
            sl.material = copies[m.name]; cnt += 1
    stats["herringbone_floor"] = {"slots": cnt, "n": n, "image": png.name}
    return cnt
