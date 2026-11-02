"""Shared helpers for the ratio-3 shells (hotel5_shell / convfloor_shell; user 2026-10-26: Codex reference-match ratio >= 0.5).
sea_panorama(kind) -> path of a generated 2048x768 sea-view panorama ('day' | 'sunset'), cached under data/venue_refs/ratio3/. Same layout as the skyline cards (horizon row ~0.41 from the top,
sea below, a strip of tree tops at the very bottom), so it can replace the image of the env-window card / the sunset pane without touching their UV mapping."""
from __future__ import annotations

import math
from pathlib import Path

OUT = Path("/jarvis/project/robomituba/data/venue_refs/ratio3")


def _fbm(h, w, rng, octaves=6, base=4, aniso=1.0):
    import numpy as np
    acc = np.zeros((h, w), np.float32); amp = 1.0; tot = 0.0
    for o in range(octaves):
        gh, gw = max(2, int(base * 2 ** o / aniso)), max(2, int(base * 2 ** o * 2))
        g = rng.random((gh + 1, gw + 1)).astype(np.float32)
        ys, xs = np.linspace(0, gh, h, endpoint=False), np.linspace(0, gw, w, endpoint=False)
        y0, x0 = ys.astype(int), xs.astype(int); fy, fx = (ys - y0)[:, None], (xs - x0)[None, :]
        fy, fx = fy * fy * (3 - 2 * fy), fx * fx * (3 - 2 * fx)
        a = g[y0][:, x0] * (1 - fx) + g[y0][:, x0 + 1] * fx; b = g[y0 + 1][:, x0] * (1 - fx) + g[y0 + 1][:, x0 + 1] * fx
        acc += (a * (1 - fy) + b * fy) * amp; tot += amp; amp *= 0.5
    return acc / tot


def sea_panorama(kind="day"):
    import numpy as np
    from PIL import Image
    OUT.mkdir(parents=True, exist_ok=True); p = OUT / f"sea_{kind}.png"
    if p.exists():
        return str(p)
    H, W = 768, 2048; hz = 315; rng = np.random.default_rng(7 if kind == "day" else 11)
    y = np.arange(H, dtype=np.float32)[:, None]; x = np.arange(W, dtype=np.float32)[None, :]
    t = np.clip(y / hz, 0, 1)                                                # 0 top .. 1 horizon
    if kind == "day":
        top, low, sunc = np.array([0.22, 0.45, 0.82]), np.array([0.72, 0.85, 0.95]), None
    else:
        top, low = np.array([0.28, 0.4, 0.68]), np.array([1.0, 0.62, 0.30])
    sky = top[None, None, :] * (1 - t[..., None] ** 1.5) + low[None, None, :] * (t[..., None] ** 1.5)
    cl = _fbm(H, W, rng, 6, 3, aniso=0.45); cl = np.clip((cl - 0.5) * 3.2, 0, 1) * np.clip(1 - t * 0.7, 0, 1)
    cc = np.array([1.0, 1.0, 1.0]) if kind == "day" else np.array([1.0, 0.72, 0.5])
    sky = sky * (1 - cl[..., None] * 0.7) + cc[None, None, :] * cl[..., None] * 0.7
    sx = 520.0
    if kind != "day":                                                         # low sun glow
        d = np.hypot((x - sx) * 0.6, (y - (hz - 40)))
        sky += np.array([1.0, 0.75, 0.35])[None, None, :] * (np.exp(-d / 90.0) * 1.2 + np.exp(-d / 420.0) * 0.5)[..., None]
        sky += np.array([1.0, 0.95, 0.8])[None, None, :] * (d < 16)[..., None] * 1.5
    # distant headlands / islands on the horizon
    ridge = _fbm(1, W, rng, 7, 3)[0]; ridge = hz - 8 - np.clip(ridge - 0.42, 0, 1) * 260 * np.exp(-((np.arange(W) - 1500) / 520.0) ** 2) \
        - np.clip(_fbm(1, W, rng, 6, 9)[0] - 0.55, 0, 1) * 150 * np.exp(-((np.arange(W) - 330) / 260.0) ** 2)
    far = np.array([0.45, 0.52, 0.68]) if kind == "day" else np.array([0.45, 0.35, 0.45])
    land = (y > ridge[None, :]) & (y < hz + 2)
    sky = np.where(land[..., None], far[None, None, :] * (0.85 + 0.3 * (y - ridge[None, :]) / 60.0).clip(0.85, 1.15)[..., None], sky)
    # sea: darker toward the viewer, ripples, sun / sky reflection, glints
    s = np.clip((y - hz) / (H - hz), 0, 1)
    if kind == "day":
        near, far_s = np.array([0.05, 0.28, 0.5]), np.array([0.35, 0.6, 0.78])
    else:
        near, far_s = np.array([0.07, 0.14, 0.3]), np.array([0.85, 0.5, 0.4])
    sea = np.broadcast_to(far_s[None, None, :] * (1 - s[..., None] ** 0.5) + near[None, None, :] * (s[..., None] ** 0.5), (H, W, 3)).copy()
    rip = _fbm(H, W, rng, 6, 40, aniso=0.12); sea *= (0.88 + 0.24 * rip)[..., None]
    gl = np.clip((rip - 0.62) * 6, 0, 1) * np.exp(-((x - (sx if kind != "day" else 900)) / (160 + 500 * s)) ** 2)
    sea += np.array([1.0, 0.85, 0.6] if kind != "day" else [1, 1, 1])[None, None, :] * gl[..., None] * (0.55 if kind != "day" else 0.25)
    img = np.where((y >= hz + 2)[..., None], sea, sky)
    # tree tops along the bottom edge
    tr = 740 - np.clip(_fbm(1, W, rng, 6, 30)[0] - 0.4, 0, 1) * 90
    trees = (y > tr[None, :]); tcol = np.array([0.08, 0.2, 0.08]) * (0.6 + 0.8 * _fbm(H, W, rng, 5, 80))[..., None]
    img = np.where(trees[..., None], tcol, img)
    Image.fromarray((np.clip(img, 0, 1) ** (1 / 1.0) * 255).astype(np.uint8)).save(p)
    return str(p)


# ------------------------------------------------------------------------------------------------------ shared kit-stage helpers (hotel5_shell / convfloor_shell ratio-3 parts)
def _h5():
    import hotel5_shell
    return hotel5_shell


def pool(key, base, rx=None, **sz):
    """Filtered copy of an asset pool under a new kind name (real_assets.abo(key, ...) then draws from it); sz = x=(lo, hi) / y / z extent limits."""
    import re
    import real_assets as ra
    P = [e for e in ra._pool(base) if (rx is None or re.search(rx, e["name"], re.I))]
    for ax, (a, b) in sz.items():
        i = "xyz".index(ax); P = [e for e in P if a <= e["extent_m"][i] <= b]
    ra._POOLS[key] = P
    return len(P)


def ids_pool(key, ids):
    import abo_assets
    import real_assets as ra
    ra._POOLS[key] = [e for e in abo_assets.entries() if e["id"] in ids]
    return len(ra._POOLS[key])


def place(kind, seed, x, y, z, yaw, fit, name):
    import real_assets as ra
    o = ra.abo(kind, seed, x, y, z, yaw, fit=fit)
    if o is not None:
        o.name = name
    return o


def hs(rx, seed, x, y, z, yaw, fit, name, **kw):
    import real_assets as ra
    o = ra.hssd(rx, seed, x, y, z, yaw, fit=fit, **kw)
    if o is not None:
        o.name = name
    return o


def recolor(m, rgb):
    """Set the albedo of a hotel5_shell._flat material (its Base Color comes through a Mix node's A input, so the BSDF default alone is ignored)."""
    b = m.node_tree.nodes["Principled BSDF"]; lk = b.inputs["Base Color"].links
    if lk and lk[0].from_node.type == "MIX":
        lk[0].from_node.inputs["A"].default_value = (*rgb, 1)
    b.inputs["Base Color"].default_value = (*rgb, 1)


def dark_tv(o):
    """A switched-off TV: one black glossy material over the whole model (the HSSD screens come in white / emissive)."""
    import bpy
    h5 = _h5()
    m = bpy.data.materials.get("ir_r3_tv") or h5._flat("ir_r3_tv", (0.008, 0.008, 0.01), 0.08)
    o.data = o.data.copy()
    for i in range(len(o.data.materials)):
        o.data.materials[i] = m


def tv(seed, x, y, z, yaw, fit, name):
    """HSSD TVs come out of the glTF importer lying on their back (thin axis = z): stand them up, then place like real_assets.abo (front -y -> yaw); grows to `fit`."""
    import random as _r
    import re
    import bpy
    import abo_assets
    import real_assets as ra
    from mathutils import Matrix
    P = [e for e in ra._pool("tv") if re.search(r"80'' Led TV|60'' Led TV|55'' Led TV|Sony Bravia|Flat Screen TV|Yoo TV", e["name"], re.I)]
    if not P:
        return None
    o = abo_assets._import(_r.Random(seed).choice(P), name)
    zs = [v.co.z for v in o.data.vertices]; ys = [v.co.y for v in o.data.vertices]
    if (max(zs) - min(zs)) < 0.5 * (max(ys) - min(ys)):
        o.data.transform(Matrix.Rotation(math.pi / 2, 4, "X")); o.data.update(); bpy.context.view_layer.update()      # bound_box is stale until the update
    ra._stand(o, x, y, z, yaw - math.atan2(ra.ABO_FRONT[1], ra.ABO_FRONT[0]), fit, grow=True)
    dark_tv(o)
    return o


def plant(slot, seed, x, y, z, h, w, yaw=0.0, name="Real_r3_plant_lib"):
    """A plant from data/plant_library_v2 (Infinigen-grown, user rule: plants are Infinigen's); slot 'atrium' = tall banana palms, 'atrium_under' = ferns / snake plants."""
    from room_planner import plant_lib2 as pl2
    m = pl2.pick(slot, seed)
    o = pl2.load(m, h, 90000, max_w=w, yaw=yaw) if m is not None else None
    if o is not None:
        o.location = (x, y, z); o.name = name
    return o


def bouquet(seed, x, y, z, k=1.0, big=True):
    """A flower arrangement with real Infinigen wild-flower stems (proc_assets FlowerArrangement / BudVase with the infinigen_plants style switched on for the call)."""
    from room_planner import proc_assets as pa
    F = pa.FlowerArrangementFactory if big else pa.BudVaseFactory
    old = pa.STYLE.get("infinigen_plants"); pa.STYLE["infinigen_plants"] = 1
    try:
        o = F(seed).spawn_asset(0)
    finally:
        if old is None:
            pa.STYLE.pop("infinigen_plants", None)
        else:
            pa.STYLE["infinigen_plants"] = old
    if o is not None:
        o.location = (x, y, z); o.scale = (k, k, k); o.name = "Real_r3_flowers"
    return o


def rug_mat(name="ir_r3_pale_rug", rgb=(0.8, 0.74, 0.64), stripes=True):
    """Pale woven wool: fine ribs (stripes) or plain, with a wool-pile bump."""
    import bpy
    h5 = _h5()
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = h5._flat(name, rgb, 0.98); nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); wv = N.new("ShaderNodeTexWave"); wv.wave_type = "BANDS"; wv.bands_direction = "X" if stripes else "Y"
    wv.inputs["Scale"].default_value = 28.0; wv.inputs["Distortion"].default_value = 1.5; wv.inputs["Detail"].default_value = 2.0; L.new(tc.outputs["Object"], wv.inputs["Vector"])
    mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.inputs["A"].default_value = (*rgb, 1); mx.inputs["B"].default_value = (rgb[0] * 0.8, rgb[1] * 0.78, rgb[2] * 0.74, 1)
    L.new(wv.outputs["Fac"], mx.inputs["Factor"]); L.new(mx.outputs["Result"], b.inputs["Base Color"])
    fine = N.new("ShaderNodeTexNoise"); fine.inputs["Scale"].default_value = 260.0; fine.inputs["Detail"].default_value = 4.0; L.new(tc.outputs["Object"], fine.inputs["Vector"])
    s = N.new("ShaderNodeMath"); s.operation = "ADD"; L.new(wv.outputs["Fac"], s.inputs[0]); L.new(fine.outputs["Fac"], s.inputs[1])
    bu = N.new("ShaderNodeBump"); bu.inputs["Strength"].default_value = 0.6; bu.inputs["Distance"].default_value = 0.004; L.new(s.outputs[0], bu.inputs["Height"]); L.new(bu.outputs["Normal"], b.inputs["Normal"])
    return m


def niche_pr():
    h5 = _h5()
    m = dict(h5._niche_mats()); m["back2"] = h5._flat("ir_r3_niche_moss", (0.09, 0.2, 0.05), 0.95)
    return m, {x: [] for x in m.values()}


def green_niche(pr, mats, axis, line, side, u, w=0.85, h=1.9, zc=1.5, seed=0):
    """A lit vertical-garden recess proud of the wall: dark moss back, bronze frame, warm LED strips top + bottom, ferns / snake plants from the plant library packed in
    (ref: illuminated leafy wall recesses). axis 0 = wall along x (line = y), 1 = wall along y (line = x); side = which way the room lies. Returns the number of plants."""
    import random as _r

    def P(a, d, z, sa, sd, sz):
        return ("box", a, line + side * d, z, sa, sd, sz) if axis == 0 else ("box", line + side * d, a, z, sd, sa, sz)
    pr[mats["back"]].append(P(u, 0.02, zc, w, 0.04, h)); pr[mats["back2"]].append(P(u, 0.045, zc, w - 0.02, 0.01, h - 0.02))
    for a_ in (u - w / 2 - 0.03, u + w / 2 + 0.03):
        pr[mats["frame"]].append(P(a_, 0.08, zc, 0.06, 0.16, h + 0.12))
    for z_ in (zc - h / 2 - 0.03, zc + h / 2 + 0.03):
        pr[mats["frame"]].append(P(u, 0.08, z_, w + 0.12, 0.16, 0.06))
    for z_ in (zc + h / 2 - 0.03, zc - h / 2 + 0.03):
        pr[mats["led"]].append(P(u, 0.1, z_, w - 0.04, 0.02, 0.016))
    rg = _r.Random(seed); n = 0
    for row, zb in enumerate([zc - h / 2 + 0.03 + 0.46 * r for r in range(max(2, int(h / 0.46)))]):
        for col in range(3 if row % 2 == 0 else 2):
            uu = u - w / 2 + w * (col + (0.5 if row % 2 == 0 else 1.0)) / 3 + rg.uniform(-0.04, 0.04)
            x_, y_ = ((uu, line + side * 0.1) if axis == 0 else (line + side * 0.1, uu))
            n += plant("atrium_under", seed * 13 + row * 3 + col, x_, y_, zb, rg.uniform(0.6, 0.95), 0.55, yaw=rg.uniform(0, 6.28), name="Real_r3_niche_plant") is not None
    return n


def sconce(pr, brass, shade, x, y, z, dx, dy, name):
    """Brass wall sconce: back plate, short arm, pleated emissive shade (a real fixture) + a soft point light. (dx, dy) = unit vector out of the wall."""
    pr[brass].append(("cyl", (x + dx * 0.005, y + dy * 0.005, z), (x + dx * 0.02, y + dy * 0.02, z), 0.05, 20))
    pr[brass].append(("cyl", (x + dx * 0.02, y + dy * 0.02, z), (x + dx * 0.1, y + dy * 0.1, z), 0.01, 8))
    pr[shade].append(("cyl", (x + dx * 0.14, y + dy * 0.14, z - 0.1), (x + dx * 0.14, y + dy * 0.14, z + 0.12), 0.07, 20))
    _h5()._light(name, "POINT", (x + dx * 0.16, y + dy * 0.16, z), 14, (1.0, 0.8, 0.55), r=0.05)


# ------------------------------------------------------------------------------------------------------ crystal ring chandelier
def _mat(name, rgb, rough=0.3, metal=0.0, emit=None, trans=0.0):
    import bpy
    from room_planner import proc_assets as pa
    m = bpy.data.materials.get(name)
    if m is None:
        m = pa._flat(name, rgb, rough, metal, transmission=trans) if trans else pa._flat(name, rgb, rough, metal); m["weathered"] = True
        if emit:
            b = m.node_tree.nodes["Principled BSDF"]; b.inputs["Emission Color"].default_value = (*emit[0], 1.0); b.inputs["Emission Strength"].default_value = emit[1]
    return m


def crystal_ring(name, cx, cy, zc, R=0.8, nstrand=84, drop=0.5, light=True):
    """Brass double ring with a warm LED band and a skirt of crystal-bead strands (ref: 'elaborate crystal-ring chandelier skirts', F1 foyer / halls / meeting rooms); returns the object.
    zc = z of the ring's centre line; the canopy cables go to z = 3.62."""
    import bmesh
    import bpy
    import random as _r
    from mathutils import Vector
    brass = _mat("ir_r3_ring_brass", (0.78, 0.6, 0.3), 0.25, 1.0); crys = _mat("ir_r3_ring_crystal", (0.97, 0.97, 1.0), 0.02, 0.0, emit=((1.0, 0.85, 0.6), 0.5), trans=1.0)
    led = _mat("ir_r3_ring_led", (1.0, 0.85, 0.6), 0.3, 0.0, emit=((1.0, 0.82, 0.55), 7.0))
    bm = bmesh.new(); rg = _r.Random(int(cx * 13 + cy * 7))

    def tube(r0, z, rad, n=72, mi=0):
        rings = []
        for k in range(8):                                              # an 8-gon tube section swept round the circle
            a = 2 * math.pi * k / 8; rr = r0 + rad * math.cos(a); zz = z + rad * math.sin(a)
            rings.append([bm.verts.new((cx + rr * math.cos(2 * math.pi * i / n), cy + rr * math.sin(2 * math.pi * i / n), zz)) for i in range(n)])
        for k in range(8):
            for i in range(n):
                f = bm.faces.new((rings[k][i], rings[k][(i + 1) % n], rings[(k + 1) % 8][(i + 1) % n], rings[(k + 1) % 8][i])); f.material_index = mi; f.smooth = True

    def cyl(p0, p1, r, seg=5, mi=0):
        d = Vector(p1) - Vector(p0); L = d.length
        res = bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r, radius2=r, depth=L)
        bmesh.ops.transform(bm, matrix=d.to_track_quat("Z", "Y").to_matrix().to_4x4(), verts=res["verts"]); bmesh.ops.translate(bm, vec=(Vector(p0) + Vector(p1)) / 2, verts=res["verts"])
        for f in {f for v in res["verts"] for f in v.link_faces}:
            f.material_index = mi

    def bead(c, r, sz=1.0, mi=1):
        res = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=r); bmesh.ops.scale(bm, vec=(1, 1, sz), verts=res["verts"]); bmesh.ops.translate(bm, vec=c, verts=res["verts"])
        for f in {f for v in res["verts"] for f in v.link_faces}:
            f.material_index = mi
    tube(R, zc, 0.03, mi=0); tube(R * 0.8, zc - 0.05, 0.02, mi=0)
    n = 72; led_r = [bm.verts.new((cx + (R - 0.035) * math.cos(2 * math.pi * i / n), cy + (R - 0.035) * math.sin(2 * math.pi * i / n), zc + zz)) for zz in (-0.012, 0.012) for i in range(n)]
    for i in range(n):
        f = bm.faces.new((led_r[i], led_r[(i + 1) % n], led_r[n + (i + 1) % n], led_r[n + i])); f.material_index = 2
    for k in range(nstrand):                                            # the skirt: two staggered rows of strands
        a = 2 * math.pi * k / nstrand; rr = R + (0.015 if k % 2 else -0.04); L = drop * rg.uniform(0.7, 1.0) * (0.75 if k % 2 else 1.0)
        x, y = cx + rr * math.cos(a), cy + rr * math.sin(a)
        cyl((x, y, zc - 0.03), (x, y, zc - 0.03 - L), 0.0025)
        for t in range(1, 8):
            bead((x, y, zc - 0.03 - L * t / 8.0), 0.0085 + 0.003 * (t % 2), 1.0)
        bead((x, y, zc - 0.03 - L), 0.018, 1.8)
    for a in (0.2, 2.3, 4.4):                                           # three suspension cables
        cyl((cx + R * math.cos(a), cy + R * math.sin(a), zc + 0.03), (cx + R * 0.3 * math.cos(a), cy + R * 0.3 * math.sin(a), 3.62), 0.003, 5)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free(); me.materials.append(brass); me.materials.append(crys); me.materials.append(led)
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    if light:
        ld = bpy.data.lights.new(name + "_l", "POINT"); ld.energy = 140.0 * R; ld.color = (1.0, 0.82, 0.58); ld.shadow_soft_size = 0.3
        lo = bpy.data.objects.new(name + "_l", ld); lo.location = (cx, cy, zc - 0.3); bpy.context.scene.collection.objects.link(lo)
    return o
