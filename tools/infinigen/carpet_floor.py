"""Carpet-tile floor (floor O review: dark blue-gray carpet tiles with irregular horizontal streaks, matte; corridors a plainer dark grey). Hooked from kit_lighting after the herringbone
floor, only when ROOM_FLOOR_CARPET is set.

    from carpet_floor import apply; stats["carpet_floor"] = apply(stats)

Env:  ROOM_FLOOR_CARPET=r,g,b            base colour, sRGB 0..1 (dark blue-grey 0.16,0.19,0.27)
      ROOM_CARPET_ROOMS=office,meeting-room   only floors whose name starts with one of these prefixes get carpet (empty = all)
      ROOM_CARPET_TILE=0.5               tile edge in metres (each tile is turned 0 / 90 deg at random, so the streaks run both ways like laid carpet tiles)
      ROOM_CARPET_VARY=0.10              per-tile tone variation (+- fraction)     ROOM_CARPET_STREAK=0.55   streak contrast 0..1     ROOM_CARPET_ROUGH=0.92   roughness
      ROOM_CARPET_PLAIN=r,g,b            colour of the plainer carpet for the rooms listed in ROOM_CARPET_PLAIN_ROOMS (comma-separated name prefixes, e.g. hallway); streak contrast 0.15
Baked into a 4096 px tileable image (8 x 8 tiles of 0.5 m = 4 m period, 1 mm per pixel; fibres = horizontal streaks of random length in navy / grey / black tones, fine speckle, a dark seam line
round every tile), cached in data/venue_refs/carpet_cache and mapped in WORLD metres (Geometry Position): continuous across room boundaries, no UVs. Floor materials are copied and replaced
as in herringbone_floor.py.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import bpy

CACHE = Path("/jarvis/project/robomituba/data/venue_refs/carpet_cache")
PX = 4096
NT = 8                                               # tiles per period edge


def _bake(base, tile, vary, streak):
    import numpy as np
    from PIL import Image
    key = hashlib.md5(repr((tuple(round(b, 3) for b in base), round(tile, 3), round(vary, 3), round(streak, 3), PX, NT, 3 if streak < 0.3 else 1)).encode()).hexdigest()[:12]
    out = CACHE / f"cp_{key}.png"
    size_m = tile * NT
    if out.exists():
        return out, size_m
    CACHE.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(int(key[:8], 16))
    tp = PX // NT
    base = np.array(base, dtype=np.float64)
    dark = base * 0.35; grey = np.array([base.mean() * 1.15] * 3) * np.array([0.95, 1.0, 1.05]); navy = base * np.array([0.8, 0.9, 1.3])
    img = np.zeros((PX, PX, 3), dtype=np.float64)
    yy, xx = np.mgrid[0:tp, 0:tp]
    for ty in range(NT):
        for tx in range(NT):
            # horizontal streaks: a random field stretched ~40x along x
            coarse = rng.random((tp, tp // 40 + 2))
            xs = np.linspace(0, coarse.shape[1] - 1.001, tp)
            i0 = xs.astype(int); fr_ = xs - i0
            st = coarse[:, i0] * (1 - fr_) + coarse[:, i0 + 1] * fr_                    # (tp, tp) streak field 0..1, long along x
            row = rng.random((tp, 1)); row = np.repeat(row, tp, axis=1)                 # a per-row tone so the lines read as fibres
            f = np.clip(0.5 + (st - 0.5) * 1.6 * streak + (row - 0.5) * 0.6 * streak, 0, 1)
            sel = rng.random((tp // 3 + 1, 1))[np.minimum(yy // 3, tp // 3)][..., 0]    # which fibre colour per 3-px band
            c1 = np.where((sel < 0.33)[..., None], navy, np.where((sel < 0.66)[..., None], grey, dark))
            if streak < 0.3:                                                             # a PLAIN carpet (B refs: uniform light grey): no coloured fibre bands, only a faint luminance streak scaled by `streak`
                col = base * (1.0 + (st[..., None] - 0.5) * 0.25 * streak * 3 + (row[..., None] - 0.5) * 0.08 * streak * 3)
            else:
                col = base * (1 - f[..., None]) * 0.9 + c1 * f[..., None] * (0.6 + 0.4 * streak) + base * 0.15 * (1 - streak)
            col *= 1.0 + (rng.random() - 0.5) * 2.0 * vary                               # this tile's tone
            col *= (1.0 + (rng.random((tp, tp, 1)) - 0.5) * 0.16)                        # fine speckle
            seam = np.minimum(np.minimum(xx, tp - 1 - xx), np.minimum(yy, tp - 1 - yy))
            if streak < 0.3:                                                             # a plain carpet (B r22: 'a pale tile'): a faint joint and a coarser fibre speckle, so it reads as carpet, not as tiled porcelain
                col *= np.where(seam < 2, 0.9 + 0.04 * seam, 1.0)[..., None]
                col *= (1.0 + (rng.random((tp // 2, tp // 2, 1)).repeat(2, 0).repeat(2, 1) - 0.5) * 0.22)
            else:
                col *= np.where(seam < 3, 0.62 + 0.12 * seam, 1.0)[..., None]            # dark tile joint
            if rng.random() < 0.5:
                col = np.rot90(col)
            img[ty * tp:(ty + 1) * tp, tx * tp:(tx + 1) * tp] = col
    Image.fromarray((np.clip(img, 0, 1) * 255.0 + 0.5).astype(np.uint8), "RGB").save(out)
    return out, size_m


def _carpet(mat, img, size_m, rough):
    nt = mat.node_tree; N, Lk = nt.nodes, nt.links
    b = next((n for n in N if n.type == "BSDF_PRINCIPLED"), None)
    if mat.get("carpet"):
        return False
    if b is None:
        N.clear(); b = N.new("ShaderNodeBsdfPrincipled"); out = N.new("ShaderNodeOutputMaterial"); Lk.new(b.outputs["BSDF"], out.inputs["Surface"])
    for l in list(b.inputs["Base Color"].links) + list(b.inputs["Roughness"].links):
        Lk.remove(l)
    geo = N.new("ShaderNodeNewGeometry"); mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (1.0 / size_m, 1.0 / size_m, 1.0)
    tx = N.new("ShaderNodeTexImage"); tx.image = img; tx.interpolation = "Smart"; tx.extension = "REPEAT"
    Lk.new(geo.outputs["Position"], mp.inputs["Vector"]); Lk.new(mp.outputs["Vector"], tx.inputs["Vector"]); Lk.new(tx.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = rough
    for nm in ("Specular IOR Level", "Specular"):
        if nm in b.inputs:
            b.inputs[nm].default_value = 0.15                    # matte: no gloss
    mat["carpet"] = True
    return True


def apply(stats):
    raw = os.environ.get("ROOM_FLOOR_CARPET")
    if not raw:
        return 0
    base = tuple(float(v) for v in raw.split(","))
    tile = float(os.environ.get("ROOM_CARPET_TILE") or 0.5)
    vary = float(os.environ.get("ROOM_CARPET_VARY") or 0.10)
    streak = float(os.environ.get("ROOM_CARPET_STREAK") or 0.55)
    rough = float(os.environ.get("ROOM_CARPET_ROUGH") or 0.92)
    plain_raw = os.environ.get("ROOM_CARPET_PLAIN")
    plain_rooms = tuple(x.strip() for x in (os.environ.get("ROOM_CARPET_PLAIN_ROOMS") or "").split(",") if x.strip())
    variants = {"main": _bake(base, tile, vary, streak)}
    if plain_raw and plain_rooms:
        variants["plain"] = _bake(tuple(float(v) for v in plain_raw.split(",")), tile, vary * 0.5, 0.15)
    imgs = {}
    for k, (png, size_m) in variants.items():
        im = bpy.data.images.load(str(png), check_existing=True); im.colorspace_settings.name = "sRGB"; imgs[k] = (im, size_m)
    only = tuple(x.strip() for x in (os.environ.get("ROOM_CARPET_ROOMS") or "").split(",") if x.strip())      # only these room-name prefixes get carpet (empty = every floor)
    cnt, copies = 0, {}
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.name.endswith(".floor") or (only and not o.name.startswith(only)):
            continue
        kind = "plain" if "plain" in imgs and o.name.startswith(plain_rooms) else "main"
        for sl in o.material_slots:
            m = sl.material
            if m is None or not m.use_nodes:
                continue
            ck = (m.name, kind)
            if ck not in copies:
                c = m.copy(); c.name = f"{m.name}.carpet_{kind}"; copies[ck] = c if _carpet(c, imgs[kind][0], imgs[kind][1], rough) else m
            sl.material = copies[ck]; cnt += 1
    stats["carpet_floor"] = {"slots": cnt, "variants": list(variants)}
    return cnt
