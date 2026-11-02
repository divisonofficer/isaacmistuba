"""Grey-floor variant of a promoted scene (IR_PIPELINE: the albedo model turns grey concrete brown on real captures, the training GT is brown-heavy on dark floors).

    blender -b -P greyfloor_variant.py -- IN.blend OUT.blend [--seed N] [--kelvin 5200..6500]

Every *.floor object gets ONE neutral grey material (R = G = B in the Principled base colour, so the albedo GT is neutral grey) chosen by room type:
    offices / meeting / closet / break    carpet tile (0.15-0.3, per-tile +-4 % value, fine speckle) or grey vinyl (0.45-0.6, rough 0.25-0.4), seeded per room
    hallways / utility / warehouse / car park / service   polished grey concrete (0.35-0.5, rough 0.3-0.6 with macro variation + faint trowel marks) or grey epoxy (0.35-0.5, rough 0.18-0.3)
    clinic rooms (exam / dental / restroom / lab)          grey vinyl
All patterns are in WORLD metres (Geometry Position), so a pattern runs on across rooms. Lamps and emissive panels with a WARM colour get a 5200-6500 K colour of the SAME luminance (intensities kept);
sun lamps 5500-6500 K; the world background colour is made neutral (luminance kept). Blue / saturated accent lights are left alone.
A JSON log (OUT.blend.greyfloor.json) lists every swap (old material, variant, grey, roughness), the per-room floor albedo (mean, B/G), the lamps changed and the kelvin used.
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
import zlib

import bpy

CARPET_TYPES = ("office", "meeting-room", "closet", "break-room", "lobby")
CLINIC_TYPES = ("exam-room", "dental-room", "restroom", "lab", "clinic", "pharmacy")


GLOSSY_ROUGH = (0.10, 0.25)                                                                       # --rough LO,HI overrides (single layer, no coat: roughness stays a GT channel)


def _kelvin_rgb(k):
    """Linear RGB (max 1) of a black-body at k kelvin (Tanner Helland fit, sRGB -> linear)."""
    t = k / 100.0
    r = 255.0 if t <= 66 else max(0.0, min(255.0, 329.698727446 * (t - 60) ** -0.1332047592))
    g = max(0.0, min(255.0, 99.4708025861 * math.log(t) - 161.1195681661)) if t <= 66 else max(0.0, min(255.0, 288.1221695283 * (t - 60) ** -0.0755148492))
    b = 255.0 if t >= 66 else (0.0 if t <= 19 else max(0.0, min(255.0, 138.5177312231 * math.log(t - 10) - 305.0447927307)))
    return tuple((c / 255.0) ** 2.2 for c in (r, g, b))


def _lum(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _same_lum(rgb, lum):
    s = lum / max(_lum(rgb), 1e-6)
    return tuple(min(1.0, c * s) for c in rgb) if max(c * s for c in rgb) <= 1.0 else tuple(c * s for c in rgb)


def _world_nodes(nt, scale):
    N, L = nt.nodes, nt.links
    geo = N.new("ShaderNodeNewGeometry"); mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = scale
    L.new(geo.outputs["Position"], mp.inputs["Vector"])
    return mp.outputs["Vector"]


def _noise(nt, vec, scale, detail=4.0, rough=0.55):
    n = nt.nodes.new("ShaderNodeTexNoise"); n.inputs["Scale"].default_value = scale; n.inputs["Detail"].default_value = detail; n.inputs["Roughness"].default_value = rough
    nt.links.new(vec, n.inputs["Vector"]); return n.outputs["Fac"]


def _mul(N, L, a, b):
    n = N.new("ShaderNodeMath"); n.operation = "MULTIPLY"; L.new(a, n.inputs[0]); L.new(b, n.inputs[1]); return n.outputs[0]


def _mat(name, variant, grey, rough, seed):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    rr = random.Random(seed); hue = None
    for nm in ("Specular IOR Level", "Specular"):
        if nm in b.inputs:
            b.inputs[nm].default_value = (0.5 if variant == "glossy" else 0.35) if variant in ("concrete", "epoxy", "vinyl", "glossy") else 0.12
    b.inputs["Metallic"].default_value = 0.0
    vec1 = _world_nodes(nt, (1.0, 1.0, 1.0))
    vm = N.new("ShaderNodeMath"); vm.operation = "MULTIPLY_ADD"; vm.use_clamp = False; vm.inputs[1].default_value = 0.0
    if variant in ("concrete", "epoxy", "glossy"):
        macro = _noise(nt, _world_nodes(nt, (0.22, 0.22, 0.22)), 1.0, 5.0, 0.6)                               # cloudy tone patches ~4 m
        mid = _noise(nt, _world_nodes(nt, (0.55, 0.55, 0.55)), 1.0, 4.0, 0.6)                                 # 1-3 m mottling
        fine = _noise(nt, vec1, 7.0, 6.0, 0.55)                                                                # pores
        tr = N.new("ShaderNodeMapping"); tr.inputs["Scale"].default_value = (0.35, 4.0, 1.0); tr.inputs["Rotation"].default_value = (0, 0, rr.uniform(0, 3.14))        # trowel marks: noise stretched along one axis
        geo = N.new("ShaderNodeNewGeometry"); L.new(geo.outputs["Position"], tr.inputs["Vector"]); trow = _noise(nt, tr.outputs["Vector"], 3.0, 2.0, 0.5)
        def madd(a_out, mul, add_out=None, add_const=0.0):
            n_ = N.new("ShaderNodeMath"); n_.operation = "MULTIPLY_ADD"; n_.inputs[1].default_value = mul; L.new(a_out, n_.inputs[0])
            if add_out is not None:
                L.new(add_out, n_.inputs[2])
            else:
                n_.inputs[2].default_value = add_const
            return n_.outputs[0]
        # value factor = 1 + 0.12 (macro-.5) + 0.12 (mid-.5) + 0.05 (fine-.5) + 0.03 (trowel-.5)  => about +-8..10 % at 1-3 m, same on R, G and B
        f = madd(macro, 0.36, None, 1.0 - 0.5 * (0.36 + 0.36 + 0.15 + 0.09))                                    # noise Fac only spans ~0.35-0.65, so x3 gives +-8-10 % at 1-3 m
        f = madd(mid, 0.36, f); f = madd(fine, 0.15, f); f = madd(trow, 0.09, f)
        # control joints every ~5 m (a thin dark line) + a few hairline cracks (distance-to-edge of a coarse voronoi, kept where a noise mask is high)
        jb = N.new("ShaderNodeTexBrick"); jb.offset = 0.0; jb.offset_frequency = 2; jb.inputs["Scale"].default_value = 1.0 / rr.uniform(4.0, 6.0); jb.inputs["Mortar Size"].default_value = 0.004; jb.inputs["Mortar Smooth"].default_value = 0.0
        jb.inputs["Brick Width"].default_value = 1.0; jb.inputs["Row Height"].default_value = 1.0; jb.inputs["Color1"].default_value = (1, 1, 1, 1); jb.inputs["Color2"].default_value = (1, 1, 1, 1); jb.inputs["Mortar"].default_value = (0, 0, 0, 1)
        L.new(_world_nodes(nt, (1.0, 1.0, 1.0)), jb.inputs["Vector"])
        sj = N.new("ShaderNodeSeparateColor"); L.new(jb.outputs["Color"], sj.inputs["Color"])                      # R = 1 on the slab, 0 on the joint
        f = _mul(N, L, f, madd(sj.outputs["Red"], 0.10, None, 0.90))                                           # joint -> 0.9
        vo = N.new("ShaderNodeTexVoronoi"); vo.feature = "DISTANCE_TO_EDGE"; vo.inputs["Scale"].default_value = 0.32; vo.inputs["Randomness"].default_value = 1.0; L.new(_world_nodes(nt, (1.0, 1.0, 1.0)), vo.inputs["Vector"])
        lt = N.new("ShaderNodeMath"); lt.operation = "LESS_THAN"; lt.inputs[1].default_value = 0.006; L.new(vo.outputs["Distance"], lt.inputs[0])
        cm_ = _noise(nt, _world_nodes(nt, (0.2, 0.2, 0.2)), 1.0, 2.0, 0.5); gt = N.new("ShaderNodeMath"); gt.operation = "GREATER_THAN"; gt.inputs[1].default_value = 0.6; L.new(cm_, gt.inputs[0])
        ck = N.new("ShaderNodeMath"); ck.operation = "MULTIPLY"; L.new(lt.outputs[0], ck.inputs[0]); L.new(gt.outputs[0], ck.inputs[1])
        f = _mul(N, L, f, madd(ck.outputs[0], -0.14, None, 1.0))                                               # crack -> 0.86
        if variant == "glossy":                                                                                  # aggregate: ~2 cm stones, each cell its own value (+-18 %), same on R, G, B
            ag = N.new("ShaderNodeTexVoronoi"); ag.feature = "F1"; ag.inputs["Scale"].default_value = 55.0; ag.inputs["Randomness"].default_value = 1.0; L.new(_world_nodes(nt, (1.0, 1.0, 1.0)), ag.inputs["Vector"])
            sg = N.new("ShaderNodeSeparateColor"); L.new(ag.outputs["Color"], sg.inputs["Color"]); f = _mul(N, L, f, madd(sg.outputs["Red"], 0.36, None, 0.82))
        fac = f
        # tiny independent hue jitter per macro blob: B/G 0.985..1.015, R/G 1.0075..0.9925
        hj = _noise(nt, _world_nodes(nt, (0.5, 0.5, 0.5)), 1.0, 2.0, 0.5); hjf = madd(hj, 0.03, None, 0.985)                      # B scale 0.985..1.015
        hjr = madd(hj, -0.015, None, 1.0075)
        mp = N.new("ShaderNodeMapRange"); lo, hi = (GLOSSY_ROUGH if variant == "glossy" else (0.3, 0.6) if variant == "concrete" else (0.18, 0.3)); mp.inputs["To Min"].default_value = lo; mp.inputs["To Max"].default_value = hi
        L.new(macro, mp.inputs["Value"]); L.new(mp.outputs["Result"], b.inputs["Roughness"])
        m["hue_b"] = True; hue = (hjr, hjf)
    elif variant == "vinyl":
        fine = _noise(nt, vec1, 40.0, 2.0, 0.5); f = N.new("ShaderNodeMath"); f.operation = "MULTIPLY_ADD"; f.inputs[1].default_value = 0.04; f.inputs[2].default_value = 0.98; L.new(fine, f.inputs[0])
        mv = _noise(nt, _world_nodes(nt, (0.4, 0.4, 0.4)), 1.0, 3.0, 0.5); mf = N.new("ShaderNodeMath"); mf.operation = "MULTIPLY_ADD"; mf.inputs[1].default_value = 0.20; mf.inputs[2].default_value = 0.90; L.new(mv, mf.inputs[0])
        fac = _mul(N, L, f.outputs[0], mf.outputs[0])
        b.inputs["Roughness"].default_value = rough
    else:                                                                                                       # carpet tile 0.5 m, per-tile +-4 % value, fine speckle
        br = N.new("ShaderNodeTexBrick"); br.offset = 0.0; br.inputs["Scale"].default_value = 1.0 / 0.5; br.inputs["Mortar Size"].default_value = 0.01; br.inputs["Brick Width"].default_value = 1.0; br.inputs["Row Height"].default_value = 1.0
        br.inputs["Color1"].default_value = (1.04, 1.04, 1.04, 1); br.inputs["Color2"].default_value = (0.96, 0.96, 0.96, 1); br.inputs["Mortar"].default_value = (0.8, 0.8, 0.8, 1); br.inputs["Mortar Smooth"].default_value = 0.0
        L.new(vec1, br.inputs["Vector"])
        sp = _noise(nt, vec1, 180.0, 1.0, 0.5); sf = N.new("ShaderNodeMath"); sf.operation = "MULTIPLY_ADD"; sf.inputs[1].default_value = 0.10; sf.inputs[2].default_value = 0.95; L.new(sp, sf.inputs[0])
        cmv = _noise(nt, _world_nodes(nt, (0.4, 0.4, 0.4)), 1.0, 3.0, 0.5); cmf = N.new("ShaderNodeMath"); cmf.operation = "MULTIPLY_ADD"; cmf.inputs[1].default_value = 0.24; cmf.inputs[2].default_value = 0.88; L.new(cmv, cmf.inputs[0])
        sep = N.new("ShaderNodeSeparateColor"); L.new(br.outputs["Color"], sep.inputs["Color"])
        mu = N.new("ShaderNodeMath"); mu.operation = "MULTIPLY"; L.new(sep.outputs["Red"], mu.inputs[0]); L.new(sf.outputs[0], mu.inputs[1]); fac = _mul(N, L, mu.outputs[0], cmf.outputs[0])
        b.inputs["Roughness"].default_value = 0.95
    gm = N.new("ShaderNodeMath"); gm.operation = "MULTIPLY"; gm.inputs[0].default_value = grey; L.new(fac, gm.inputs[1])
    cm = N.new("ShaderNodeCombineColor")
    if hue is None:
        [L.new(gm.outputs[0], cm.inputs[i]) for i in range(3)]
    else:
        L.new(_mul(N, L, gm.outputs[0], hue[0]), cm.inputs[0]); L.new(gm.outputs[0], cm.inputs[1]); L.new(_mul(N, L, gm.outputs[0], hue[1]), cm.inputs[2])
    L.new(cm.outputs["Color"], b.inputs["Base Color"])
    if variant == "epoxy" and "Coat Weight" in b.inputs:
        b.inputs["Coat Weight"].default_value = 0.35; b.inputs["Coat Roughness"].default_value = 0.1
    m["greyfloor"] = variant; m["weathered"] = True; b["weathered"] = True
    return m


def _variant(room_type, rr):
    if room_type in CLINIC_TYPES:
        return "vinyl"
    if room_type in CARPET_TYPES:
        return rr.choice(("carpet", "carpet", "vinyl"))
    return rr.choice(("concrete", "concrete", "epoxy"))


def _measure_rooms(log, tag=""):
    """Render a top-down patch at the middle of each floor; fills r['measured_rgb_ratio'] (linear mean R/G, B/G of the central half of a 30 deg top-down view)."""
    import numpy as np
    from mathutils import Vector
    sc = bpy.context.scene; sc.render.engine = "CYCLES"; sc.cycles.device = "CPU"; sc.cycles.samples = 32; sc.cycles.use_denoising = False
    sc.render.resolution_x, sc.render.resolution_y = 160, 120; sc.render.image_settings.file_format = "OPEN_EXR"; sc.render.image_settings.color_depth = "32"
    cam = bpy.data.objects.get("gf_cam")
    if cam is None:
        cd = bpy.data.cameras.new("gf_cam"); cam = bpy.data.objects.new("gf_cam", cd); sc.collection.objects.link(cam); cd.angle = math.radians(30); cd.clip_start = 0.05
    sc.camera = cam; cam.rotation_euler = (0, 0, 0)
    for r in log["floors"]:
        f = bpy.data.objects[r["object"]]; q = [f.matrix_world @ Vector(c) for c in f.bound_box]
        c = sum(q, Vector()) / 8; fz = max(p.z for p in q)
        r["bbox"] = [min(p.x for p in q), max(p.x for p in q), min(p.y for p in q), max(p.y for p in q), fz]
        dg = bpy.context.evaluated_depsgraph_get(); best = None                                                  # a floor point with bare floor under the whole patch (no table / rug / rack in it)
        for gx in range(-3, 4):
            for gy in range(-3, 4):
                px_, py_ = c.x + gx * (max(p.x for p in q) - min(p.x for p in q)) / 9, c.y + gy * (max(p.y for p in q) - min(p.y for p in q)) / 9
                ok_all = True
                for ox, oy in ((0, 0), (0.45, 0), (-0.45, 0), (0, 0.45), (0, -0.45), (0.45, 0.45), (-0.45, -0.45), (0.45, -0.45), (-0.45, 0.45)):
                    ok, loc, n_, i_, ob_, m_ = bpy.context.scene.ray_cast(dg, Vector((px_ + ox, py_ + oy, fz + 2.0)), Vector((0, 0, -1)))
                    if not ok or ob_.name != f.name:
                        ok_all = False; break
                if ok_all:
                    d_ = (px_ - c.x) ** 2 + (py_ - c.y) ** 2
                    if best is None or d_ < best[0]:
                        best = (d_, px_, py_)
        px0, py0 = (best[1], best[2]) if best else (c.x, c.y); r["patch_clear"] = best is not None; r["patch_xy"] = [round(px0, 2), round(py0, 2)]
        cam.location = (px0, py0, fz + 1.6)
        tmp = f"/tmp/gf_measure_{os.getpid()}.exr"; sc.render.filepath = tmp; bpy.ops.render.render(write_still=True)
        im = bpy.data.images.load(tmp, check_existing=False); im.colorspace_settings.name = "Non-Color"
        px = np.array(im.pixels[:], dtype=np.float64).reshape(-1, 4)[:, :3]; h = 120; w = 160
        px = px.reshape(h, w, 3)[h // 4:3 * h // 4, w // 4:3 * w // 4].reshape(-1, 3).mean(axis=0)
        r["measured_rgb"] = [round(float(v), 5) for v in px]; r["measured_rgb_ratio"] = {"R_over_G": round(float(px[0] / px[1]), 4), "B_over_G": round(float(px[2] / px[1]), 4)}
        bpy.data.images.remove(im); os.remove(tmp)


def _balance(log, tol=0.02, rounds=3):
    sc = bpy.context.scene; r_ = sc.render; keep = (sc.render.engine, sc.cycles.device, sc.cycles.samples, sc.cycles.use_denoising, r_.resolution_x, r_.resolution_y, r_.image_settings.file_format, r_.image_settings.color_depth, r_.filepath, sc.camera)
    try:
        _balance_loop(log, tol, rounds)
    finally:
        (sc.render.engine, sc.cycles.device, sc.cycles.samples, sc.cycles.use_denoising, r_.resolution_x, r_.resolution_y, r_.image_settings.file_format, r_.image_settings.color_depth, r_.filepath, sc.camera) = keep


def _balance_loop(log, tol=0.02, rounds=3):
    """Closed loop: scale the lamps that sit inside each room (R by G/R, B by G/B of its measured floor patch, luminance kept) until the rendered mid-floor patch is R = G = B within tol."""
    from mathutils import Vector
    log["balance"] = []
    for it in range(rounds + 1):
        _measure_rooms(log)
        worst = max(max(abs(r["measured_rgb_ratio"]["R_over_G"] - 1), abs(r["measured_rgb_ratio"]["B_over_G"] - 1)) for r in log["floors"])
        log["balance"].append({"round": it, "worst_dev": round(worst, 4), "rooms": {r["room"]: r["measured_rgb_ratio"] for r in log["floors"]}})
        if worst <= tol or it == rounds:
            break
        boxes = [tuple(r["bbox"][:4]) for r in log["floors"]]
        inside = lambda o: any(b0 - 0.3 <= o.matrix_world.translation.x <= b1 + 0.3 and c0 - 0.3 <= o.matrix_world.translation.y <= c1 + 0.3 for b0, b1, c0, c1 in boxes)
        glob = [o for o in bpy.data.objects if o.type == "LIGHT" and (o.data.type == "SUN" or not inside(o))]                  # suns / area lamps outside every room: they light the rooms through windows
        bad = [r for r in log["floors"] if it >= 1 and (abs(r["measured_rgb_ratio"]["R_over_G"] - 1) > tol or abs(r["measured_rgb_ratio"]["B_over_G"] - 1) > tol)]      # a room the local lamps could not fix
        if bad:
            grg = sum(r["measured_rgb_ratio"]["R_over_G"] for r in bad) / len(bad); gbg = sum(r["measured_rgb_ratio"]["B_over_G"] for r in bad) / len(bad)
            for o in glob:
                d = o.data
                if d.users > 1:
                    d = o.data = d.copy()
                c = tuple(d.color); d.color = _same_lum((c[0] / grg, c[1], c[2] / gbg), _lum(c))
        for r in log["floors"]:
            rg, bg = r["measured_rgb_ratio"]["R_over_G"], r["measured_rgb_ratio"]["B_over_G"]
            if abs(rg - 1) <= tol and abs(bg - 1) <= tol:
                continue
            x0, x1, y0, y1, fz = r["bbox"]
            for o in bpy.data.objects:
                if o.type == "LIGHT" and o.data.type != "SUN" and x0 - 0.3 <= o.matrix_world.translation.x <= x1 + 0.3 and y0 - 0.3 <= o.matrix_world.translation.y <= y1 + 0.3:
                    d = o.data
                    if d.users > 1:
                        d = o.data = d.copy()
                    c = tuple(d.color); n = (c[0] / rg, c[1], c[2] / bg); d.color = _same_lum(n, _lum(c))
    for r in log["floors"]:
        log["rooms"][r["room"]]["measured_rgb_ratio"] = r["measured_rgb_ratio"]; r.pop("bbox", None)


def main(argv):
    a = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    src, dst = a[0], a[1]
    seed = int(a[a.index("--seed") + 1]) if "--seed" in a else 7
    rng = random.Random(seed)
    kelvin = float(a[a.index("--kelvin") + 1]) if "--kelvin" in a else rng.uniform(5800, 6500)
    global GLOSSY_ROUGH
    if "--rough" in a:
        GLOSSY_ROUGH = tuple(float(x) for x in a[a.index("--rough") + 1].split(","))
    floor_mode = a[a.index("--floor") + 1] if "--floor" in a else None                                          # force one floor variant everywhere (e.g. glossy)
    keep_lights = "--keep-lights" in a                                                                         # leave lamps, emissive panels and world as they are
    bpy.ops.wm.open_mainfile(filepath=src)
    log = {"source": src, "out": dst, "seed": seed, "kelvin": round(kelvin), "floors": [], "rooms": {}, "lights": [], "emissive": [], "world": None}
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.name.endswith(".floor"):
            continue
        room = o.name[:-len(".floor")]; rtype = room.split("_")[0]
        rr = random.Random(zlib.crc32(f"{seed}:{room}".encode()))
        var = floor_mode or _variant(rtype, rr)
        grey, rough = {"carpet": (rr.uniform(0.15, 0.30), 0.95), "vinyl": (rr.uniform(0.45, 0.60), rr.uniform(0.25, 0.40)), "concrete": (rr.uniform(0.35, 0.50), 0.45), "epoxy": (rr.uniform(0.35, 0.50), 0.24), "glossy": (rr.uniform(0.35, 0.50), sum(GLOSSY_ROUGH) / 2)}[var]
        mname = f"ir_grey_{var}_{round(grey, 3)}"
        m = _mat(mname, var, grey, rough, zlib.crc32(mname.encode()))
        olds = []
        for sl in o.material_slots:
            olds.append(sl.material.name if sl.material else None); sl.material = m
        if not o.material_slots:
            o.data.materials.append(m)
        log["floors"].append({"object": o.name, "room": room, "variant": var, "grey": round(grey, 4), "roughness": round(rough, 3), "old_materials": olds})
        log["rooms"][room] = {"variant": var, "mean_albedo": round(grey, 4), "B_over_G": 1.0}
    k0 = _kelvin_rgb(kelvin); log["kelvin_lights_total"] = len(bpy.data.lights)
    for l in ([] if keep_lights else bpy.data.lights):
        c = tuple(l.color)
        if c[2] > c[0] * 1.05 or (max(c) - min(c)) / max(max(c), 1e-6) > 0.6:                                  # a blue / strongly saturated accent: leave
            continue
        kk = rng.uniform(5500, 6500) if l.type == "SUN" else kelvin
        new = _same_lum(_kelvin_rgb(kk), _lum(c) if _lum(c) > 0 else 1.0)
        log["lights"].append({"light": l.name, "type": l.type, "old": [round(x, 3) for x in c], "new": [round(x, 3) for x in new], "kelvin": round(kk)})
        l.color = new
    def _warm(c):
        return not (c[2] > c[0] * 1.05 or (max(c) - min(c)) / max(max(c), 1e-6) > 0.6)
    trees = [(m.name, m.node_tree) for m in bpy.data.materials if m.use_nodes] + [(f"group:{g.name}", g) for g in bpy.data.node_groups if g.bl_idname == "ShaderNodeTree"]
    for mname_, nt in ([] if keep_lights else trees):
        for n in nt.nodes:
            if n.type == "BSDF_PRINCIPLED" and n.inputs["Emission Strength"].default_value > 0 and not n.inputs["Emission Color"].is_linked:
                sock = n.inputs["Emission Color"]
            elif n.type == "EMISSION" and not n.inputs["Color"].is_linked and n.inputs["Strength"].default_value > 0:
                sock = n.inputs["Color"]
            elif n.type == "BLACKBODY":
                n.inputs["Temperature"].default_value = kelvin; log["emissive"].append({"material": mname_, "node": "blackbody", "kelvin": round(kelvin)}); continue
            else:
                continue
            c = tuple(sock.default_value)[:3]
            if not _warm(c):
                continue
            new = _same_lum(k0, _lum(c) if _lum(c) > 0 else 1.0); sock.default_value = (*new, 1.0)
            log["emissive"].append({"material": mname_, "old": [round(x, 3) for x in c], "new": [round(x, 3) for x in new]})
    w = bpy.context.scene.world
    if w is not None and w.use_nodes and not keep_lights:
        for n in w.node_tree.nodes:
            if n.type == "BACKGROUND" and not n.inputs["Color"].is_linked:
                c = tuple(n.inputs["Color"].default_value)[:3]; new = _same_lum(_kelvin_rgb(6500), _lum(c) if _lum(c) > 0 else 0.5)
                n.inputs["Color"].default_value = (*new, 1.0); log["world"] = {"old": [round(x, 3) for x in c], "new": [round(x, 3) for x in new]}
    bpy.ops.wm.save_as_mainfile(filepath=dst)
    if "--no-measure" not in a:
        _balance(log)
        gc = bpy.data.objects.get("gf_cam")
        if gc is not None:
            bpy.data.objects.remove(gc, do_unlink=True)
        bpy.ops.wm.save_as_mainfile(filepath=dst)
        json.dump(log, open(dst + ".greyfloor.json", "w"), indent=1)
    json.dump(log, open(dst + ".greyfloor.json", "w"), indent=1)
    print("GREYFLOOR", len(log["floors"]), "floors", len(log["lights"]), "lights", "K", log["kelvin"])


if __name__ == "__main__":
    main(sys.argv)
