"""Chevron floor stripes (O5 creative office ref: the work area's oak floor carries teal / blue / mint / grey chevron bands). Hooked from kit_lighting after the patchwork floor, only when
ROOM_FLOOR_STRIPES=1.

    from floor_stripes import apply; stats["floor_stripes"] = apply(stats)

Env: ROOM_STRIPE_ROOMS=break-room_0/3   floor-name prefixes that get it (empty = every floor)
     ROOM_STRIPE_RGB="0.1,0.5,0.55;0.2,0.35,0.6;0.6,0.85,0.72;0.6,0.62,0.64"   band colours, sRGB 0..1, cycled across the field
     ROOM_STRIPE_W=0.6 band width (m)   ROOM_STRIPE_AMP=0.5 zig-zag amplitude (m)   ROOM_STRIPE_WAVE=1.2 zig-zag wavelength (m)   ROOM_STRIPE_ROUGH=0.45   ROOM_STRIPE_BASE=0.74,0.6,0.42 oak plank base seen between nothing (none: bands touch)
The bands run along y and zig-zag in x (a V pattern); 4.8 m tile baked to data/venue_refs/tile_cache/stripes_<hash>.png (4096 px), mapped in WORLD metres (Geometry Position), faint 15 cm plank seams
along x so it still reads as a wood floor. Floor materials are copied and replaced as in patchwork_floor.py."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import bpy

CACHE = Path("/jarvis/project/robomituba/data/venue_refs/tile_cache")
PX, TILE = 4096, 4.8
DEFAULT = "0.1,0.5,0.55;0.2,0.35,0.6;0.6,0.85,0.72;0.6,0.62,0.64"


def _bake(cols, w, amp, wave):
    import numpy as np
    from PIL import Image
    key = hashlib.md5(repr((cols, w, amp, wave, PX, TILE)).encode()).hexdigest()[:10]
    out = CACHE / f"stripes_{key}.png"
    if out.exists():
        return out
    CACHE.mkdir(parents=True, exist_ok=True)
    n = len(cols)
    w_eff = TILE / max(1, round(TILE / (w * n))) / n                  # a whole number of colour cycles per tile so the image tiles
    wv = TILE / max(1, round(TILE / wave))
    xs = (np.arange(PX) + 0.5) / PX * TILE
    x, y = np.meshgrid(xs, xs)
    tri = np.abs(((y / wv) % 1.0) * 2 - 1) * 2 - 1                    # triangle wave -1..1 along y
    band = np.floor((x + amp * tri) / w_eff).astype(np.int64) % n
    img = np.array(cols, dtype=np.float64)[band]
    rng = np.random.default_rng(int(key[:6], 16))
    row = np.floor(y / 0.15).astype(np.int64)
    tone = 1.0 + (rng.random(int(TILE / 0.15) + 2)[row % int(TILE / 0.15)] - 0.5) * 0.06
    seam = (np.mod(y, 0.15) < 0.0015)[..., None]
    img = img * tone[..., None] * np.where(seam, 0.8, 1.0)
    Image.fromarray((np.clip(img, 0, 1) ** (1 / 1.0) * 255.0 + 0.5).astype(np.uint8), "RGB").save(out)
    return out


def _mat(mat, img, rough):
    nt = mat.node_tree; N_, Lk = nt.nodes, nt.links
    b = next((n for n in N_ if n.type == "BSDF_PRINCIPLED"), None)
    if mat.get("stripes"):
        return False
    if b is None:
        N_.clear(); b = N_.new("ShaderNodeBsdfPrincipled"); out = N_.new("ShaderNodeOutputMaterial"); Lk.new(b.outputs["BSDF"], out.inputs["Surface"])
    for l in list(b.inputs["Base Color"].links) + list(b.inputs["Roughness"].links):
        Lk.remove(l)
    geo = N_.new("ShaderNodeNewGeometry"); mp = N_.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (1.0 / TILE, 1.0 / TILE, 1.0)
    tx = N_.new("ShaderNodeTexImage"); tx.image = img; tx.interpolation = "Smart"; tx.extension = "REPEAT"
    Lk.new(geo.outputs["Position"], mp.inputs["Vector"]); Lk.new(mp.outputs["Vector"], tx.inputs["Vector"]); Lk.new(tx.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = rough
    mat["stripes"] = True
    return True


def apply(stats):
    if os.environ.get("ROOM_FLOOR_STRIPES") != "1":
        return 0
    cols = tuple(tuple(float(v) for v in c.split(",")) for c in (os.environ.get("ROOM_STRIPE_RGB") or DEFAULT).split(";"))
    w = float(os.environ.get("ROOM_STRIPE_W") or 0.6); amp = float(os.environ.get("ROOM_STRIPE_AMP") or 0.5); wave = float(os.environ.get("ROOM_STRIPE_WAVE") or 1.2)
    rough = float(os.environ.get("ROOM_STRIPE_ROUGH") or 0.45)
    png = _bake(cols, w, amp, wave)
    img = bpy.data.images.load(str(png), check_existing=True); img.colorspace_settings.name = "sRGB"
    only = tuple(x.strip() for x in (os.environ.get("ROOM_STRIPE_ROOMS") or "").split(",") if x.strip())
    cnt, copies = 0, {}
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.name.endswith(".floor") or (only and not o.name.startswith(only)):
            continue
        for sl in o.material_slots:
            m = sl.material
            if m is None or not m.use_nodes:
                continue
            if m.name not in copies:
                c = m.copy(); c.name = f"{m.name}.stripes"; copies[m.name] = c if _mat(c, img, rough) else m
            sl.material = copies[m.name]; cnt += 1
    stats["floor_stripes"] = {"slots": cnt, "image": png.name}
    return cnt
