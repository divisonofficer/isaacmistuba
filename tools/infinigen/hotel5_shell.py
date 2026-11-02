"""H5 hotel floor shell (kit stage, idempotent via scene["ir_hotel5_shell"]); ROOM_HOTEL5_SHELL=1 enables every part, ROOM_HOTEL5_SKIP=<comma list of clean,lounge,elev,corr,beds,spare,ensuite,stalls,kitchen,lobby,hall,rooms2,lounge2,lifts,corr2,ensuite2> switches parts off.
Rooms: break-room_0/0 sky lounge (0-10 x 8-22), hallway_0/0 elevator hall (10-20 x 0-8), hallway_0/1 guest corridor (10-46 x 8-11), bedroom_0/N guest rooms, break-room_0/1 banquet lobby (46-55 x 0-11), dining-room_0/0 banquet hall (46-58 x 11-22); ceiling 3.7 m.
clean   no Infinigen columns / pilasters / exposed beams anywhere
lounge  sunset-city window walls (emissive picture panes + mullions) on the west / north walls, curved mezzanine slab + cove on 3 brass round columns, warm marble floor, warm area lights
elev    4 dark bronze lift doors on the south wall, wood-panel walls with lit green niches, marble floor with veining, cove-lit ceiling
corr    patterned carpet + marble-inlay border strips, wood panels between the doors, lit green niches, cove strips, downlights
beds    warm ceiling light per guest room, grey upholstered headboard wall behind each bed
lobby   marble floor with blue / gold inlay border, dark wood + gold lattice feature wall (east), warm lights
hall    coffered ceiling with 2 sunburst crystal chandeliers, swirl carpet, white round tablecloths, chair covers with blue sashes
light   warm downlight spots in the public rooms
"""
from __future__ import annotations

import math
import os
import random

import bpy
import ratio3_common as rc
import real_assets as ra
from mathutils import Vector

ZC = 3.7
LOUNGE, ELEV, CORR, LOBBY, HALL = "break-room_0/0", "hallway_0/0", "hallway_0/1", "break-room_0/1", "dining-room_0/0"


def _bb(o):
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]


def _room(name):
    import wall_face                                             # the box out to the walls' INNER faces: corridor / partition walls sit ~0.13 m inside the floor box, so pieces at box + 1-5 cm were buried (audit 10-25)
    return wall_face.inner_box(name)


def _fbox(f):
    import wall_face
    return wall_face.inner_box(f.name[:-6])


def _fl():
    from room_planner import proc_boutique_flagship as fl
    return fl


def _pa():
    from room_planner import proc_assets as pa
    return pa


def _flat(name, rgb, rough=0.5, metal=0.0):
    m = _pa()._flat(name, rgb, rough, metal); m["weathered"] = True
    return m


def _emit(name, rgb, strength):
    m = _flat(name, rgb, 0.4); b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Emission Color"].default_value = (*rgb, 1.0); b.inputs["Emission Strength"].default_value = strength
    return m


def _wood(name, rgb):
    m = bpy.data.materials.get(name)
    if m is None:
        m = _flat(name, rgb, 0.4); _pa()._grain(m, rgb)
    return m


def _noise_mix(name, c1, c2, scale, rough=0.3, detail=6.0, distort=1.0, wave=False):
    """Floor / carpet colour: noise (or wave) in object space mixing c1 and c2."""
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = _flat(name, c1, rough); nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"
    if wave:
        t = N.new("ShaderNodeTexWave"); t.wave_type = "BANDS"; t.bands_direction = "DIAGONAL"; t.inputs["Scale"].default_value = scale; t.inputs["Distortion"].default_value = 6.0; t.inputs["Detail"].default_value = 3.0
    else:
        t = N.new("ShaderNodeTexNoise"); t.inputs["Scale"].default_value = scale; t.inputs["Detail"].default_value = detail; t.inputs["Distortion"].default_value = distort
    L.new(tc.outputs["Object"], t.inputs["Vector"])
    mx.inputs["A"].default_value = (*c1, 1); mx.inputs["B"].default_value = (*c2, 1)
    mr = N.new("ShaderNodeMapRange"); mr.inputs["From Min"].default_value = 0.35; mr.inputs["From Max"].default_value = 0.65      # noise Fac clusters round 0.5: stretch it, or the pattern reads as one flat colour (H5 r4 corridor)
    L.new(t.outputs["Fac"], mr.inputs["Value"]); L.new(mr.outputs["Result"], mx.inputs["Factor"]); L.new(mx.outputs["Result"], b.inputs["Base Color"])
    return m


def _set_floor(room, mat):
    f = bpy.data.objects.get(f"{room}.floor")
    if f is not None:
        for sl in f.material_slots:
            sl.material = mat


def _set_ceiling(room, mat):
    c = bpy.data.objects.get(f"{room}.ceiling")
    if c is not None:
        for sl in c.material_slots:
            sl.material = mat


def _rm_ceiling_clutter(lo, hi, names=("CeilingGridFactory", "LinearLedFactory", "DiffuserFactory", "DropCeilingFactory", "CeilingLightFactory", "CeilingBeamFactory", "SoffitFactory", "TrackRailFactory", "TrackSpotFactory", "AboCeilingFixtureFactory", "SprinklerFactory")):
    for o in list(bpy.data.objects):
        if o.name.startswith(names):
            b0, b1 = _bb(o); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
            if lo[0] - 0.3 <= cx <= hi[0] + 0.3 and lo[1] - 0.3 <= cy <= hi[1] + 0.3 and b1[2] > 2.0:
                bpy.data.objects.remove(o, do_unlink=True)


def _light(name, kind, loc, energy, rgb=(1.0, 0.8, 0.58), **kw):
    ld = bpy.data.lights.new(name, kind); ld.energy = energy * float(os.environ.get("ROOM_HOTEL5_LIGHT") or 0.08); ld.color = rgb
    if kind == "AREA":
        ld.shape = kw.get("shape", "RECTANGLE"); ld.size = kw.get("sx", 1.0); ld.size_y = kw.get("sy", 1.0)
    elif kind == "SPOT":
        ld.spot_size = math.radians(80); ld.spot_blend = 0.6; ld.shadow_soft_size = 0.05
    else:
        ld.shadow_soft_size = kw.get("r", 0.1)
    o = bpy.data.objects.new(name, ld); o.location = loc; bpy.context.scene.collection.objects.link(o)
    return o


def _door_gaps(axis, line, lo, hi, pad=0.12):
    """Intervals along `axis` (0 = x, 1 = y) occupied by doors / openings whose bbox touches the wall line (other-axis coordinate `line`)."""
    out = []
    o_ax = 1 - axis
    for o in bpy.data.objects:
        if o.type == "MESH" and (o.name.startswith(("door", "DoorCasing", "LiteDoor", "GlassPanelDoor", "PanelDoor", "Window")) or o.name == "door"):
            b0, b1 = _bb(o)
            if b0[o_ax] - 0.35 <= line <= b1[o_ax] + 0.35 and b1[axis] > lo and b0[axis] < hi:
                out.append((b0[axis] - pad, b1[axis] + pad))
    return sorted(out)


def _segments(lo, hi, gaps, minw=0.5):
    segs, cur = [], lo
    for a, b in gaps:
        if a - cur >= minw:
            segs.append((cur, a))
        cur = max(cur, b)
    if hi - cur >= minw:
        segs.append((cur, hi))
    return segs


def _clad(name, mat, axis, line, side, lo, hi, z0, z1, gaps, t=0.04):
    """Wall panelling boxes along axis between the door gaps. axis 0: wall runs along x at y=line; side +1 / -1 = which way the room lies from the wall."""
    prims = []
    for a, b in _segments(lo, hi, gaps):
        c = (a + b) / 2; w = b - a
        prims.append(("box", c, line + side * t / 2, (z0 + z1) / 2, w, t, z1 - z0) if axis == 0 else ("box", line + side * t / 2, c, (z0 + z1) / 2, t, w, z1 - z0))
    if prims:
        _fl().mesh_object(name, [(mat, prims)], bevel=False)
    return len(prims)


def _clean(stats):
    k = 0
    for o in list(bpy.data.objects):
        if o.name.startswith(("ColumnFactory", "RoundPillarFactory", "PilasterFactory", "CeilingBeamFactory")):
            bpy.data.objects.remove(o, do_unlink=True); k += 1
    stats["h5_clean_removed"] = k


def _sunset(name, axis, line, a0, a1, z0, z1, side, strength=1.7):
    """An emissive 'window' flush on the wall face at `line` (axis 0: along x, 1: along y): the skyline panorama (bigglass_cards/src/skyline.png) tinted to dusk, plus mullions (H5 r4 ENV-01: the gradient + hard silhouette read as a flat peach wall)."""
    fl = _fl(); pa = _pa()
    m = bpy.data.materials.get("ir_h5_sunset")
    if m is None:
        m = pa._flat("ir_h5_sunset", (0.9, 0.5, 0.2), 0.5); m["weathered"] = True
        nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
        tc = N.new("ShaderNodeTexCoord"); mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (0.55, 0.55, 1.0); mp.inputs["Location"].default_value = (0.2, 0.3, 0.0)
        im = N.new("ShaderNodeTexImage"); im.image = bpy.data.images.load("/jarvis/project/robomituba/data/venue_refs/bigglass_cards/src/skyline.png", check_existing=True); im.extension = "EXTEND"
        L.new(tc.outputs["UV"], mp.inputs["Vector"]); L.new(mp.outputs["Vector"], im.inputs["Vector"])
        tint = N.new("ShaderNodeMix"); tint.data_type = "RGBA"; tint.blend_type = "MULTIPLY"; tint.inputs["Factor"].default_value = 0.75; tint.inputs["B"].default_value = (1.0, 0.62, 0.38, 1)
        L.new(im.outputs["Color"], tint.inputs["A"])
        L.new(tint.outputs["Result"], b.inputs["Base Color"]); L.new(tint.outputs["Result"], b.inputs["Emission Color"]); b.inputs["Emission Strength"].default_value = strength
    e = 0.02 * side
    if axis == 0:
        quad = [(a0, line + e, z0), (a1, line + e, z0), (a1, line + e, z1), (a0, line + e, z1)]
    else:
        quad = [(line + e, a0, z0), (line + e, a1, z0), (line + e, a1, z1), (line + e, a0, z1)]
    from room_planner import rooftop_shell as rs
    rs._quads(name, [quad], m)
    fr = _flat("ir_h5_mullion", (0.05, 0.05, 0.055), 0.4, 1.0); prims = []; n = max(2, int((a1 - a0) // 1.6)); step = (a1 - a0) / n
    for i in range(n + 1):
        c = a0 + i * step
        prims.append(("box", c, line + side * 0.05, (z0 + z1) / 2, 0.08, 0.08, z1 - z0) if axis == 0 else ("box", line + side * 0.05, c, (z0 + z1) / 2, 0.08, 0.08, z1 - z0))
    for z in (z0, (z0 + z1) / 2, z1):
        prims.append(("box", (a0 + a1) / 2, line + side * 0.05, z, a1 - a0, 0.08, 0.06) if axis == 0 else ("box", line + side * 0.05, (a0 + a1) / 2, z, 0.08, a1 - a0, 0.06))
    fl.mesh_object(name + "Frame", [(fr, prims)], bevel=False)


def _lounge(stats):
    lo, hi = _room(LOUNGE)
    if lo is None:
        return
    fl = _fl()
    _rm_ceiling_clutter(lo, hi)
    _set_ceiling(LOUNGE, _flat("ir_h5_ceil", (0.9, 0.88, 0.84), 0.6))
    _set_floor(LOUNGE, _noise_mix("ir_h5_marble_warm", (0.8, 0.72, 0.6), (0.62, 0.52, 0.42), 2.0, rough=0.18, distort=1.5))
    _sunset("H5SunsetW", 1, lo[0] + 0.05, lo[1] + 0.6, hi[1] - 0.6, 0.15, 3.55, 1)       # west wall x = 0.05, along y
    _sunset("H5SunsetN", 0, hi[1] - 0.05, lo[0] + 0.5, hi[0] - 0.3, 0.15, 3.55, -1)       # north wall
    br = _flat("ir_h5_brass", (0.72, 0.52, 0.22), 0.3, 1.0); cream = _flat("ir_h5_cream", (0.93, 0.9, 0.82), 0.5)
    glow = _emit("ir_h5_cove", (1.0, 0.78, 0.5), 3.0)
    cx, cy, R = lo[0], (lo[1] + hi[1]) / 2, 6.3; zs = 2.75
    pts = [(cx + R * math.cos(math.radians(a)), cy + R * math.sin(math.radians(a))) for a in range(-90, 91, 10)]
    import bmesh
    bm = bmesh.new(); ctr = bm.verts.new((cx, cy, zs)); ring = [bm.verts.new((x, y, zs)) for x, y in pts]
    for i in range(len(ring) - 1):
        bm.faces.new((ctr, ring[i], ring[i + 1]))
    me = bpy.data.meshes.new("H5MezzSlab"); bm.to_mesh(me); bm.free(); me.materials.append(cream)
    o = bpy.data.objects.new("H5MezzSlab", me); bpy.context.scene.collection.objects.link(o)
    sol = o.modifiers.new("s", "SOLIDIFY"); sol.thickness = 0.3; sol.offset = 1.0
    prims, gl = [], []
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2; ln = math.hypot(x1 - x0, y1 - y0); yaw = math.atan2(y1 - y0, x1 - x0)
        prims.append(("box", mx, my, zs - 0.15 - 0.25, ln + 0.02, 0.1, 0.5, yaw))
        gl.append(("box", mx - 0.12 * math.cos(yaw + math.pi / 2) * -1, my - 0.12 * math.sin(yaw + math.pi / 2) * -1, zs - 0.42, ln, 0.04, 0.03, yaw))
    fl.mesh_object("H5MezzFascia", [(cream, prims), (glow, gl)], bevel=False)
    cols = [("cyl", (cx + R * math.cos(math.radians(a)), cy + R * math.sin(math.radians(a)), 0.1), (cx + R * math.cos(math.radians(a)), cy + R * math.sin(math.radians(a)), zs), 0.3, 24) for a in (-55, 0, 55)]
    fl.mesh_object("H5LoungeColumns", [(br, cols)], bevel=False)
    rail = []; gl = _pa()._flat("ir_h5_railglass", (0.85, 0.9, 0.92), 0.03, transmission=0.9); gl["weathered"] = True
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        rail.append(("box", (x0 + x1) / 2, (y0 + y1) / 2, zs + 0.3 + 0.5, math.hypot(x1 - x0, y1 - y0) + 0.01, 0.02, 0.9, math.atan2(y1 - y0, x1 - x0)))
    fl.mesh_object("H5MezzRail", [(gl, rail), (br, [(p_[0], p_[1], p_[2], zs + 1.27, *p_[4:6], 0.05, p_[7]) for p_ in rail])], bevel=False)
    rug = _flat("ir_h5_rug", (0.86, 0.82, 0.74), 0.95)
    fl.mesh_object("H5LoungeRug", [(rug, [("cyl", (cx + 3.2, cy, 0.135), (cx + 3.2, cy, 0.145), 2.6, 48)])], bevel=False)
    for i, (x, y) in enumerate(((3.0, 11.5), (3.0, 18.5), (7.5, 15.0))):
        _light(f"ir_h5_lounge_{i}", "AREA", (x, y, 3.3), 600, sx=2.5, sy=2.5)
    _light("ir_h5_lounge_sun", "AREA", (1.0, cy, 2.0), 700, (1.0, 0.6, 0.3), sx=0.5, sy=10.0).rotation_euler = (0, math.radians(90), 0)
    stats["h5_lounge"] = 1


def _elev(stats):
    lo, hi = _room(ELEV)
    if lo is None:
        return
    fl = _fl()
    _rm_ceiling_clutter(lo, hi)
    _set_ceiling(ELEV, _flat("ir_h5_ceil", (0.9, 0.88, 0.84), 0.6))
    _set_floor(ELEV, _noise_mix("ir_h5_marble_brown", (0.82, 0.72, 0.6), (0.42, 0.28, 0.22), 1.3, rough=0.15, distort=2.0))
    wood = _wood("ir_h5_wood", (0.62, 0.43, 0.22)); bronze = _flat("ir_h5_lift", (0.16, 0.1, 0.07), 0.3, 1.0); glow = _emit("ir_h5_cove", (1.0, 0.78, 0.5), 3.0)
    ys = lo[1] + 0.12
    _clad("H5ElevWallS", wood, 0, ys, 1, lo[0] + 0.1, hi[0] - 0.1, 0.1, ZC - 0.35, [])
    doors = [("box", x, ys + 0.1, 1.3, 1.5, 0.05, 2.5) for x in (11.8, 14.3, 15.7, 18.2)]
    frames = [("box", x, ys + 0.08, 1.3, 1.65, 0.04, 2.62) for x in (11.8, 14.3, 15.7, 18.2)]
    fl.mesh_object("H5LiftDoors", [(bronze, doors)], bevel=False)
    green = _emit("ir_h5_niche", (0.2, 0.5, 0.15), 1.6); gold = _flat("ir_h5_gold", (0.8, 0.62, 0.25), 0.3, 1.0)
    nich = [("box", lo[0] + 0.14, 4.0, 1.7, 0.03, 1.0, 1.5), ("box", hi[0] - 0.14, 4.0, 1.7, 0.03, 1.0, 1.5)]
    fl.mesh_object("H5ElevNiches", [(green, nich), (gold, [("box", lo[0] + 0.12, 4.0, 2.46, 0.04, 1.1, 0.04), ("box", hi[0] - 0.12, 4.0, 2.46, 0.04, 1.1, 0.04)])], bevel=False)
    cove = [("box", (lo[0] + hi[0]) / 2, lo[1] + 0.3, ZC - 0.2, hi[0] - lo[0] - 0.6, 0.12, 0.04), ("box", (lo[0] + hi[0]) / 2, hi[1] - 0.3, ZC - 0.2, hi[0] - lo[0] - 0.6, 0.12, 0.04),
            ("box", lo[0] + 0.3, (lo[1] + hi[1]) / 2, ZC - 0.2, 0.12, hi[1] - lo[1] - 0.6, 0.04), ("box", hi[0] - 0.3, (lo[1] + hi[1]) / 2, ZC - 0.2, 0.12, hi[1] - lo[1] - 0.6, 0.04)]
    fl.mesh_object("H5ElevCove", [(glow, cove)], bevel=False)
    for i, (x, y) in enumerate(((13, 2.5), (17, 2.5), (13, 6), (17, 6))):
        _light(f"ir_h5_elev_{i}", "AREA", (x, y, 3.4), 350, sx=1.5, sy=1.5)
    stats["h5_elev"] = 1


def _corr(stats):
    lo, hi = _room(CORR)
    if lo is None:
        return
    fl = _fl()
    _rm_ceiling_clutter(lo, hi)
    _set_ceiling(CORR, _flat("ir_h5_ceil", (0.9, 0.88, 0.84), 0.6))
    _set_floor(CORR, _noise_mix("ir_h5_carpet_patch", (0.5, 0.36, 0.3), (0.84, 0.76, 0.64), 0.9, rough=0.85, distort=3.0))
    mar = _noise_mix("ir_h5_marble_brown", (0.82, 0.72, 0.6), (0.42, 0.28, 0.22), 1.3, rough=0.15, distort=2.0)
    wood = _wood("ir_h5_wood", (0.62, 0.43, 0.22)); glow = _emit("ir_h5_cove", (1.0, 0.78, 0.5), 3.0); green = _emit("ir_h5_niche", (0.2, 0.5, 0.15), 1.6)
    x0, x1 = lo[0] + 0.1, hi[0] - 0.1
    fl.mesh_object("H5CorrBorder", [(mar, [("box", (x0 + x1) / 2, lo[1] + 0.45, 0.112, x1 - x0, 0.5, 0.02), ("box", (x0 + x1) / 2, hi[1] - 0.45, 0.112, x1 - x0, 0.5, 0.02)])], bevel=False)
    for nm, line, side in (("S", lo[1] + 0.003, 1), ("N", hi[1] - 0.003, -1)):      # lo / hi are the inner wall faces now (wall_face): flush, not 5 cm off
        gaps = _door_gaps(0, line, x0, x1)
        n = _clad(f"H5CorrWood{nm}", wood, 0, line, side, x0, x1, 0.1, ZC - 0.3, gaps)
        niches = [("box", (a + b) / 2, line + side * 0.05, 1.7, 0.9, 0.03, 1.5) for a, b in _segments(x0, x1, gaps, 1.4)][::2]
        if niches:
            fl.mesh_object(f"H5CorrNiche{nm}", [(green, niches)], bevel=False)
    cove = [("box", (x0 + x1) / 2, lo[1] + 0.25, ZC - 0.18, x1 - x0, 0.14, 0.04), ("box", (x0 + x1) / 2, hi[1] - 0.25, ZC - 0.18, x1 - x0, 0.14, 0.04)]
    fl.mesh_object("H5CorrCove", [(glow, cove)], bevel=False)
    k = int((x1 - x0) // 3.0)
    for i in range(k):
        _light(f"ir_h5_corr_{i}", "AREA", (x0 + (i + 0.5) * (x1 - x0) / k, (lo[1] + hi[1]) / 2, 3.4), 220, sx=1.2, sy=0.8)
    stats["h5_corr"] = 1


def _beds(stats):
    grey = _flat("ir_h5_headboard", (0.5, 0.48, 0.46), 0.8); n = 0
    for o in list(bpy.data.objects):
        if o.type == "MESH" and o.name.startswith("bedroom_0/") and o.name.endswith(".floor"):
            rn = o.name[:-6]; lo, hi = _fbox(o)
            _light(f"ir_h5_bed_{rn}", "AREA", ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, ZC - 0.15), 320, sx=2.0, sy=2.0); n += 1
            bed = [b for b in bpy.data.objects if b.type == "MESH" and b.name.startswith("SoftBedFactory") and lo[0] < _bb(b)[0][0] + 0.1 < hi[0] and lo[1] < (_bb(b)[0][1] + _bb(b)[1][1]) / 2 < hi[1]]
            if not bed:
                continue
            b0, b1 = _bb(bed[0]); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
            d = {"W": cx - lo[0], "E": hi[0] - cx, "S": cy - lo[1], "N": hi[1] - cy}; w = min(d, key=d.get)
            prim = {"W": ("box", lo[0] + 0.05, cy, 1.4, 0.06, b1[1] - b0[1] + 0.9, 2.2), "E": ("box", hi[0] - 0.05, cy, 1.4, 0.06, b1[1] - b0[1] + 0.9, 2.2),
                    "S": ("box", cx, lo[1] + 0.05, 1.4, b1[0] - b0[0] + 0.9, 0.06, 2.2), "N": ("box", cx, hi[1] - 0.05, 1.4, b1[0] - b0[0] + 0.9, 0.06, 2.2)}[w]
            _fl().mesh_object(f"H5Headboard({rn})", [(grey, [prim])], bevel=False)
    stats["h5_beds"] = n


def _lobby(stats):
    lo, hi = _room(LOBBY)
    if lo is None:
        return
    fl = _fl()
    _rm_ceiling_clutter(lo, hi)
    _set_ceiling(LOBBY, _flat("ir_h5_ceil", (0.9, 0.88, 0.84), 0.6))
    _set_floor(LOBBY, _noise_mix("ir_h5_marble_cream", (0.88, 0.8, 0.68), (0.7, 0.6, 0.48), 1.6, rough=0.1, distort=2.0))
    blue = _flat("ir_h5_inlay_blue", (0.2, 0.3, 0.5), 0.15); gold = _flat("ir_h5_gold", (0.8, 0.62, 0.25), 0.3, 1.0)
    ix0, ix1, iy0, iy1 = lo[0] + 1.2, hi[0] - 1.2, lo[1] + 1.2, hi[1] - 1.5
    box = lambda cx, cy, sx, sy, z: ("box", cx, cy, z, sx, sy, 0.014)
    ring = [box((ix0 + ix1) / 2, iy0, ix1 - ix0, 0.35, 0.111), box((ix0 + ix1) / 2, iy1, ix1 - ix0, 0.35, 0.111), box(ix0, (iy0 + iy1) / 2, 0.35, iy1 - iy0, 0.111), box(ix1, (iy0 + iy1) / 2, 0.35, iy1 - iy0, 0.111)]
    line = [box((ix0 + ix1) / 2, iy0 + 0.22, ix1 - ix0, 0.03, 0.12), box((ix0 + ix1) / 2, iy1 - 0.22, ix1 - ix0, 0.03, 0.12), box(ix0 + 0.22, (iy0 + iy1) / 2, 0.03, iy1 - iy0, 0.12), box(ix1 - 0.22, (iy0 + iy1) / 2, 0.03, iy1 - iy0, 0.12)]
    fl.mesh_object("H5LobbyInlay", [(blue, ring), (gold, line)], bevel=False)
    dk = _wood("ir_h5_wood_dark", (0.2, 0.11, 0.06)); emis = _emit("ir_h5_lattice_glow", (1.0, 0.7, 0.35), 3.0); gl = _flat("ir_h5_gold", (0.8, 0.62, 0.25), 0.3, 1.0)
    xw = hi[0] - 0.08; ya, yb = lo[1] + 1.0, hi[1] - 1.0
    fl.mesh_object("H5LatticeBack", [(dk, [("box", xw, (ya + yb) / 2, 1.9, 0.04, yb - ya, 3.4)]), (emis, [("box", xw - 0.02, (ya + yb) / 2, 1.9, 0.02, yb - ya - 0.2, 3.0)])], bevel=False)
    bars = [("box", xw - 0.07, y, 1.9, 0.05, 0.05, 3.2) for y in [ya + 0.15 + i * 0.3 for i in range(int((yb - ya - 0.3) // 0.3))]] + [("box", xw - 0.07, (ya + yb) / 2, z, 0.05, yb - ya - 0.2, 0.05) for z in [0.4 + i * 0.3 for i in range(10)]]
    fl.mesh_object("H5LatticeBars", [(gl, bars)], bevel=False)
    for i, (x, y) in enumerate(((48.5, 3), (52.5, 3), (48.5, 8), (52.5, 8))):
        _light(f"ir_h5_lobby_{i}", "AREA", (x, y, 3.4), 450, sx=1.5, sy=1.5)
    stats["h5_lobby"] = 1


def _pleated(name, mat, cx, cy, r_top, z_top, z_bot, folds=36, depth=0.025, seg=144, rings=10):
    """A round tablecloth: flat top disc + a skirt that hangs to z_bot with soft folds deepening toward the hem (radius r(theta, t) = r_top + t * depth * (0.6 + 0.4 sin(folds theta))), smooth-shaded."""
    import bmesh
    bm = bmesh.new(); top = []
    c = bm.verts.new((cx, cy, z_top))
    rings_v = []
    for j in range(rings + 1):
        t = j / rings; z = z_top - t * (z_top - z_bot); ring = []
        for i in range(seg):
            a = 2 * math.pi * i / seg; r = r_top + 0.004 + t * t * depth * (0.6 + 0.4 * math.sin(folds * a)) + t * 0.02
            ring.append(bm.verts.new((cx + math.cos(a) * r, cy + math.sin(a) * r, z)))
        rings_v.append(ring)
    for i in range(seg):
        bm.faces.new((c, rings_v[0][i], rings_v[0][(i + 1) % seg]))
    for j in range(rings):
        for i in range(seg):
            bm.faces.new((rings_v[j][i], rings_v[j + 1][i], rings_v[j + 1][(i + 1) % seg], rings_v[j][(i + 1) % seg]))
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free(); me.materials.append(mat)
    for p_ in me.polygons:
        p_.use_smooth = True
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    sol = o.modifiers.new("s", "SOLIDIFY"); sol.thickness = 0.003
    return o


def _bow(bm, x, y, z, yaw, mi):
    """A satin bow on a chair back: two flattened loop lobes (UV spheres), a knot and two tails, built in bm at (x, y, z) facing yaw."""
    import bmesh
    from mathutils import Matrix
    new = []
    for sx in (-1, 1):
        r = bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=1.0); vs = r["verts"]
        bmesh.ops.scale(bm, vec=(0.075, 0.018, 0.045), verts=vs); bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(sx * 0.35, 3, "Y"), verts=vs); bmesh.ops.translate(bm, vec=(sx * 0.065, 0, 0), verts=vs); new += vs
    r = bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=8, radius=1.0); bmesh.ops.scale(bm, vec=(0.022, 0.02, 0.026), verts=r["verts"]); new += r["verts"]
    for sx in (-1, 1):
        r = bmesh.ops.create_cube(bm, size=1.0); vs = r["verts"]; bmesh.ops.scale(bm, vec=(0.035, 0.006, 0.17), verts=vs)
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(sx * 0.3, 3, "Y"), verts=vs); bmesh.ops.translate(bm, vec=(sx * 0.03, 0.004, -0.1), verts=vs); new += vs
    bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(yaw, 3, "Z"), verts=new); bmesh.ops.translate(bm, vec=(x, y, z), verts=new)
    for f in {f for v in new for f in v.link_faces}:
        f.material_index = mi


def _hall(stats):
    lo, hi = _room(HALL)
    if lo is None:
        return
    fl = _fl(); rng = random.Random(5)
    _rm_ceiling_clutter(lo, hi)
    cream = _flat("ir_h5_ceil", (0.9, 0.88, 0.84), 0.6); _set_ceiling(HALL, cream)
    _set_floor(HALL, _noise_mix("ir_h5_swirl", (0.78, 0.66, 0.5), (0.42, 0.34, 0.3), 1.4, rough=0.85, wave=True))
    glow = _emit("ir_h5_cove", (1.0, 0.8, 0.55), 4.0); gold = _flat("ir_h5_gold", (0.8, 0.62, 0.25), 0.3, 1.0)
    nx, ny = 3, 2; W, D = hi[0] - lo[0], hi[1] - lo[1]; beams, coves = [], []
    for i in range(nx + 1):
        beams.append(("box", lo[0] + W * i / nx, (lo[1] + hi[1]) / 2, ZC - 0.1, 0.35, D, 0.2))
    for j in range(ny + 1):
        beams.append(("box", (lo[0] + hi[0]) / 2, lo[1] + D * j / ny, ZC - 0.1, W, 0.35, 0.2))
    for i in range(nx):
        for j in range(ny):
            cx, cy = lo[0] + W * (i + 0.5) / nx, lo[1] + D * (j + 0.5) / ny
            for sx, sy, ox, oy in ((W / nx - 0.5, 0.06, 0, 1), (W / nx - 0.5, 0.06, 0, -1), (0.06, D / ny - 0.5, 1, 0), (0.06, D / ny - 0.5, -1, 0)):
                coves.append(("box", cx + ox * (W / nx / 2 - 0.3), cy + oy * (D / ny / 2 - 0.3), ZC - 0.21, sx, sy, 0.02))
    fl.mesh_object("H5Coffers", [(cream, beams), (glow, coves)], bevel=False)
    for k, (cx, cy) in enumerate(((lo[0] + W / 3 * 0.5 + 0.0, (lo[1] + hi[1]) / 2), (lo[0] + W * 5 / 6, (lo[1] + hi[1]) / 2))):
        cx = lo[0] + W * (1 + 2 * k) / 4; z0 = ZC - 0.8; spikes = []
        for t in range(64):
            a = 2 * math.pi * t / 64; el = rng.uniform(-0.5, 0.5) + (0.3 if t % 2 else -0.1); L = 0.55 + 0.25 * (t % 3) / 2
            dx, dy, dz = math.cos(a) * math.cos(el), math.sin(a) * math.cos(el), math.sin(el)
            spikes.append(("cyl", (cx + dx * 0.12, cy + dy * 0.12, z0 + dz * 0.12), (cx + dx * L, cy + dy * L, z0 + dz * L), 0.012, 5))
        crys = _emit("ir_h5_crystal", (1.0, 0.92, 0.75), 6.0)
        if ra.abo("chandelier", 3 + k, cx, cy, ZC - 1.1, 0.0, fit=(1.3, 1.3, 1.1)) is not None:    # audit H5-4: a real crystal chandelier
            _light(f"ir_h5_chand_{k}", "POINT", (cx, cy, z0), 900, (1.0, 0.85, 0.62), r=0.3); continue
        fl.mesh_object(f"H5Chandelier{k}", [(crys, spikes), (gold, [("cyl", (cx, cy, ZC), (cx, cy, z0 + 0.1), 0.012, 6), ("cyl", (cx, cy, z0 - 0.08), (cx, cy, z0 + 0.1), 0.14, 14)])], bevel=False)
        _light(f"ir_h5_chand_{k}", "POINT", (cx, cy, z0), 900, (1.0, 0.85, 0.62), r=0.3)
    for i, x in enumerate((lo[0] + W / 6, lo[0] + W / 2, lo[0] + W * 5 / 6)):
        for j, y in enumerate((lo[1] + D / 4, lo[1] + D * 3 / 4)):
            _light(f"ir_h5_hall_{i}_{j}", "AREA", (x, y, ZC - 0.3), 350, sx=2.0, sy=2.0)
    cloth = _flat("ir_h5_cloth", (0.95, 0.95, 0.93), 0.85); sash = _flat("ir_h5_sash", (0.12, 0.22, 0.5), 0.5); cover = _flat("ir_h5_cover", (0.94, 0.94, 0.92), 0.85)
    tp, cp = [], []; nt = nc = 0
    for o in list(bpy.data.objects):
        if o.type != "MESH":
            continue
        b0, b1 = _bb(o); c = ((b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2)
        if not (lo[0] < c[0] < hi[0] and lo[1] < c[1] < hi[1]) or b0[2] > 0.5:
            continue
        if o.name.startswith(("BreakTableFactory", "TableDiningFactory")) and b1[2] > 0.6 and b1[0] - b0[0] > 0.8:      # r4: the banquet layout's dining_table is a TableDiningFactory
            r_ = min(max(math.hypot(b1[0] - b0[0], b1[1] - b0[1]) / 2 + 0.06, 0.8), 1.35); zt = b1[2] + 0.015      # r6: the table corners poked through: cover the diagonal
            tp.append(("cyl", (c[0], c[1], 0.1), (c[0], c[1], zt - 0.02), r_ - 0.04, 28)); tp.append(("cyl", (c[0], c[1], zt - 0.02), (c[0], c[1], zt), r_, 28)); nt += 1
        elif o.name.startswith(("CafeChairFactory", "ChairFactory", "OfficeChairFactory", "DiningChairFactory")) and b1[2] < 1.3:
            cp.append((o, c)); nc += 1
    tables = [(t_[1][0], t_[1][1], t_[2][2], t_[3]) for t_ in tp[1::2]]
    for i_, (tx, ty, tz, tr) in enumerate(tables):              # r8 review: pleated cloths that hang in folds (no flat cylinders)
        _pleated(f"H5Tablecloth{i_}", cloth, tx, ty, tr, tz, 0.16)
    bm_c = __import__("bmesh").new(); pushed = 0
    for o, c in cp:                                               # chairs off the table rim (the backs clipped the cloth), facing their table; white cover skirt + blue bow on the back
        if not tables:
            break
        tx, ty, tz, tr = min(tables, key=lambda t_: (t_[0] - c[0]) ** 2 + (t_[1] - c[1]) ** 2)
        dx, dy = c[0] - tx, c[1] - ty; dist = math.hypot(dx, dy) or 1.0; ux, uy = dx / dist, dy / dist
        if dist < tr + 0.32:
            o.location.x += ux * (tr + 0.32 - dist); o.location.y += uy * (tr + 0.32 - dist); pushed += 1; dist = tr + 0.32
        px, py = tx + ux * dist, ty + uy * dist; yaw = math.atan2(uy, ux) + math.pi / 2
        _bow(bm_c, px + ux * 0.2, py + uy * 0.2, 0.8, yaw, 1)
    if cp and tables:
        me = bpy.data.meshes.new("H5ChairBows"); bm_c.to_mesh(me); bm_c.free(); me.materials.append(cover); me.materials.append(sash)
        for p_ in me.polygons:
            p_.use_smooth = True
        ob_ = bpy.data.objects.new("H5ChairBows", me); bpy.context.scene.collection.objects.link(ob_)
        for o, c in cp:                                           # the chair itself in a white slip cover (seat + back fabric), the frame kept
            if o.type == "MESH" and o.data.materials:
                o.data = o.data.copy()
                for i in range(len(o.data.materials)):
                    o.data.materials[i] = cover
    stats["h5_hall_chairs_pushed"] = pushed
    if tp:
        plate = _flat("ir_h5_plate", (0.96, 0.96, 0.94), 0.2); glass = _flat("ir_h5_glass", (0.8, 0.85, 0.9), 0.05); nap = _flat("ir_h5_napkin", (0.12, 0.22, 0.5), 0.8); fw = _flat("ir_h5_flowers", (0.96, 0.95, 0.9), 0.7); gr = _flat("ir_h5_stems", (0.2, 0.4, 0.18), 0.7)
        pp, gp, npr, fp, sp_ = [], [], [], [], []
        for t_ in tp[1::2]:
            cx, cy, zt = t_[1][0], t_[1][1], t_[2][2]; rr = t_[3]
            for k in range(6):
                a_ = 2 * math.pi * k / 6 + 0.3; px, py = cx + math.cos(a_) * (rr - 0.3), cy + math.sin(a_) * (rr - 0.3)
                if ra.lib("PlateFactory", 100 + k, px, py, zt, 0.0, 0.92, mat=plate) is None:
                    pp.append(("cyl", (px, py, zt), (px, py, zt + 0.015), 0.13, 16))
                for nm_, off in (("LibForkFactory", -0.17), ("LibKnifeFactory", 0.17)):
                    qx, qy = px + math.cos(a_ + math.pi / 2) * off, py + math.sin(a_ + math.pi / 2) * off
                    ra.lib(nm_, 600 + k, qx, qy, zt + 0.002, a_, 1.0)
                if ra.abo("napkin", 700 + k, px - math.cos(a_) * 0.2, py - math.sin(a_) * 0.2, zt, a_, fit=(0.14, 0.14, 0.05)) is None:
                    npr.append(("box", px - math.cos(a_) * 0.2, py - math.sin(a_) * 0.2, zt + 0.02, 0.1, 0.1, 0.03, a_))
                gx, gy = cx + math.cos(a_ + 0.35) * (rr - 0.18), cy + math.sin(a_ + 0.35) * (rr - 0.18)
                if ra.lib("WineglassFactory", 200 + k, gx, gy, zt, 0.0, 1.4) is None:
                    gp.append(("cyl", (gx, gy, zt), (gx, gy, zt + 0.13), 0.03, 10))
            if (ra.abo("bouquet", int(cx * 10) % 97, cx, cy, zt, 0.0, fit=(0.45, 0.45, 0.55)) or ra.abo("smallplant", int(cx * 10) % 97, cx, cy, zt, 0.0, fit=(0.45, 0.45, 0.45))) is not None:
                continue
            sp_.append(("cyl", (cx, cy, zt), (cx, cy, zt + 0.3), 0.012, 6)); fp.append(("cyl", (cx, cy, zt + 0.28), (cx, cy, zt + 0.42), 0.13, 12))
        fl.mesh_object("H5PlaceSettings", [(plate, pp), (glass, gp), (nap, npr), (fw, fp), (gr, sp_)], bevel=False)

    stats["h5_hall"] = {"tables": nt, "chairs": nc}


def _rbb(name):
    return _room(name)


def _in_room(o, lo, hi):
    b0, b1 = _bb(o); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
    return lo[0] < cx < hi[0] and lo[1] < cy < hi[1]


def _ensuites(stats):
    """LAY-02: the bath fixtures of a guest room get a partition room: walls 2.4 m round their bbox + 12 cm on the sides that are not the room's own walls, a 0.85 m door gap on the side nearest the room door, tile floor.
    A room too small to carry it (> 55 % of its floor) loses the toilet and the shower instead."""
    tile = _tile_mat(); wall = _flat("ir_h5_partition", (0.9, 0.88, 0.84), 0.6); fl = _fl(); n = d = 0
    for f in list(bpy.data.objects):
        if not (f.type == "MESH" and f.name.startswith("bedroom_0/") and f.name.endswith(".floor")):
            continue
        lo, hi = _fbox(f)
        fx = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("ToiletFactory", "ToiletStallFactory", "HomeVanityFactory", "WashBasinFactory", "ShowerEnclosureFactory")) and _in_room(o, lo, hi)]
        if not fx:
            continue
        bs = [_bb(o) for o in fx]; c = 0.12
        x0, x1 = min(b[0][0] for b in bs) - c, max(b[1][0] for b in bs) + c; y0, y1 = min(b[0][1] for b in bs) - c, max(b[1][1] for b in bs) + c
        x0, y0, x1, y1 = max(x0, lo[0]), max(y0, lo[1]), min(x1, hi[0]), min(y1, hi[1])
        if (x1 - x0) * (y1 - y0) > 0.55 * (hi[0] - lo[0]) * (hi[1] - lo[1]):
            for o in fx:
                if o.name.startswith(("ToiletFactory", "ShowerEnclosureFactory")):
                    bpy.data.objects.remove(o, do_unlink=True); d += 1
            continue
        doors = [_bb(o) for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("LiteDoor", "GlassPanelDoor", "PanelDoor", "door")) and _in_room(o, lo, hi)]
        dc = ((sum((b[0][0] + b[1][0]) / 2 for b in doors) / len(doors)), (sum((b[0][1] + b[1][1]) / 2 for b in doors) / len(doors))) if doors else ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2)
        sides = {"W": (x0, None), "E": (x1, None), "S": (None, y0), "N": (None, y1)}
        free = [k for k, (xx, yy) in sides.items() if not ((k == "W" and x0 - lo[0] < 0.3) or (k == "E" and hi[0] - x1 < 0.3) or (k == "S" and y0 - lo[1] < 0.3) or (k == "N" and hi[1] - y1 < 0.3))]
        mid = {"W": (x0, (y0 + y1) / 2), "E": (x1, (y0 + y1) / 2), "S": ((x0 + x1) / 2, y0), "N": ((x0 + x1) / 2, y1)}
        gap = min(free, key=lambda k: (mid[k][0] - dc[0]) ** 2 + (mid[k][1] - dc[1]) ** 2) if free else None
        prims = []; t = 0.08; h = 2.4
        for k in free:
            along_x = k in ("S", "N"); a0, a1 = (x0, x1) if along_x else (y0, y1); line = mid[k][1] if along_x else mid[k][0]
            spans = [(a0, a1)]
            if k == gap and a1 - a0 > 1.3:
                cc = (a0 + a1) / 2 + 0.0; spans = [(a0, cc - 0.425), (cc + 0.425, a1)]
            for u0, u1 in spans:
                if u1 - u0 < 0.1:
                    continue
                prims.append(("box", (u0 + u1) / 2, line, h / 2 + 0.1, u1 - u0, t, h) if along_x else ("box", line, (u0 + u1) / 2, h / 2 + 0.1, t, u1 - u0, h))
        if prims:
            fl.mesh_object(f"H5Ensuite({f.name[:-6]})", [(wall, prims)], bevel=False)
        fl.mesh_object(f"H5EnsuiteFloor({f.name[:-6]})", [(tile, [("box", (x0 + x1) / 2, (y0 + y1) / 2, 0.135, x1 - x0, y1 - y0, 0.01)])], bevel=False); n += 1
    stats["h5_ensuites"] = {"built": n, "dropped_fixtures": d}


def _tile_mat():
    import lux_shell
    return lux_shell._tile("ir_h5_bath_tile", (0.82, 0.78, 0.7), 0.15, size=0.3, grout=0.004)


def _stalls(stats):
    """LAY-02: laminate partitions + doors round every toilet of the restrooms: panels run from the toilet's wall out 1.5 m on both sides, a door panel closes the front with a 5 cm gap."""
    fl = _fl(); lam = _flat("ir_h5_laminate", (0.55, 0.5, 0.42), 0.5); n = 0
    for f in list(bpy.data.objects):
        if not (f.type == "MESH" and f.name.startswith("restroom_0/") and f.name.endswith(".floor")):
            continue
        lo, hi = _fbox(f)
        for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("ToiletFactory", "ToiletStallFactory")) and _in_room(o, lo, hi)]:
            b0, b1 = _bb(o); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
            d = {"W": cx - lo[0], "E": hi[0] - cx, "S": cy - lo[1], "N": hi[1] - cy}; w = min(d, key=d.get)
            L, half = 1.5, 0.48; prims = []; zc = 0.15 + 0.95; hh = 1.9
            if w in ("W", "E"):
                sg = 1 if w == "W" else -1; wx = lo[0] if w == "W" else hi[0]
                for dy in (-half, half):
                    prims.append(("box", wx + sg * L / 2, cy + dy, zc, L, 0.03, hh))
                dx = wx + sg * L
                for a, b in ((cy - half, cy - 0.45), (cy + 0.45, cy + half)):
                    prims.append(("box", dx, (a + b) / 2, zc, 0.03, b - a, hh))
            else:
                sg = 1 if w == "S" else -1; wy = lo[1] if w == "S" else hi[1]
                for dx_ in (-half, half):
                    prims.append(("box", cx + dx_, wy + sg * L / 2, zc, 0.03, L, hh))
                dy = wy + sg * L
                for a, b in ((cx - half, cx - 0.45), (cx + 0.45, cx + half)):
                    prims.append(("box", (a + b) / 2, dy, zc, b - a, 0.03, hh))
            fl.mesh_object(f"H5Stall({f.name[:-6]}|{n})", [(lam, prims)], bevel=False); n += 1
    stats["h5_stalls"] = n


def _kitchen(stats):
    """FUN-01: the prep room (2 x 11 m) gets a steel worktop run with a sink along the east wall, wall shelving above it, and two banquet trolleys."""
    lo, hi = _room("kitchen_0/0")
    if lo is None:
        return
    fl = _fl(); steel = _flat("ir_h5_steel", (0.75, 0.76, 0.78), 0.25, 1.0); body = _flat("ir_h5_prep_body", (0.62, 0.64, 0.66), 0.4, 1.0); dark = _flat("ir_h5_sink", (0.12, 0.12, 0.13), 0.3, 1.0)
    xr = hi[0] - 0.38; y0, y1 = lo[1] + 0.4, hi[1] - 0.4
    ctr = [("box", xr, (y0 + y1) / 2, 0.45, 0.7, y1 - y0, 0.9)]; top = [("box", xr, (y0 + y1) / 2, 0.915, 0.74, y1 - y0, 0.04)]
    sink = [("box", xr, (y0 + y1) / 2, 0.93, 0.5, 0.7, 0.03), ("cyl", (xr - 0.15, (y0 + y1) / 2 + 0.3, 1.0), (xr - 0.15, (y0 + y1) / 2 + 0.3, 1.25), 0.02, 8), ("box", xr - 0.15, (y0 + y1) / 2 + 0.3, 1.27, 0.03, 0.15, 0.03)]
    shelves = [("box", hi[0] - 0.15, (y0 + y1) / 2, 1.5 + 0.4 * k, 0.3, y1 - y0 - 0.5, 0.03) for k in range(3)]
    sup = [("box", hi[0] - 0.15, y0 + 0.3 + i * (y1 - y0 - 0.6) / 4, 1.7, 0.03, 0.03, 0.9) for i in range(5)]
    trol = []
    for yt in (lo[1] + 2.2, lo[1] + 5.5):
        cx = lo[0] + 0.55
        trol += [("box", cx, yt, 0.9, 0.55, 1.0, 0.03), ("box", cx, yt, 0.5, 0.55, 1.0, 0.03), ("box", cx, yt, 0.12, 0.55, 1.0, 0.03)]
        for sx in (-0.25, 0.25):
            for sy in (-0.47, 0.47):
                trol.append(("cyl", (cx + sx, yt + sy, 0.12), (cx + sx, yt + sy, 1.35), 0.015, 6))
        trol.append(("box", cx + 0.27, yt, 1.3, 0.03, 1.0, 0.05))
    rg = random.Random(11); white = _flat("ir_h5_plate", (0.96, 0.96, 0.94), 0.2); card = _flat("ir_h5_cardbox", (0.6, 0.48, 0.32), 0.8); film = _flat("ir_h5_film", (0.85, 0.88, 0.9), 0.15); glass = _flat("ir_h5_glass", (0.8, 0.85, 0.9), 0.05)
    pl, pans, boxes, films, racks = [], [], [], [], []
    xs = hi[0] - 0.15
    for k in range(3):
        z = 1.5 + 0.4 * k + 0.015; y = y0 + 0.4
        while y < y1 - 0.5:
            c_ = rg.random(); w_ = 0.3
            if c_ < 0.3:
                for q in range(rg.randint(4, 8)):                        # a stack of library plates
                    if ra.lib("PlateFactory", 300 + k, xs, y, z + q * 0.022, 0.0, 0.85, mat=white) is None:
                        pl.append(("cyl", (xs, y, z), (xs, y, z + rg.uniform(0.1, 0.22)), 0.12, 16)); break
            elif c_ < 0.5:
                nm_ = rg.choice(("PanFactory", "PotFactory", "BowlFactory"))
                if ra.lib(nm_, 400 + int(y * 10), xs, y, z, rg.uniform(0, 6.28), 0.8) is None:
                    pans.append(("cyl", (xs, y, z), (xs, y, z + 0.1), 0.13, 16)); pans.append(("cyl", (xs, y, z + 0.1), (xs, y, z + 0.2), 0.11, 16))
            elif c_ < 0.75:
                boxes.append(("box", xs, y, z + 0.12, 0.26, 0.28, 0.24)); w_ = 0.32
            elif c_ < 0.85:
                films.append(("cyl", (xs, y - 0.15, z + 0.05), (xs, y + 0.15, z + 0.05), 0.05, 12))
            else:
                racks.append(("box", xs, y, z + 0.05, 0.28, 0.4, 0.1)); w_ = 0.45
                for i in range(3):
                    for j in range(4):
                        racks.append(("cyl", (xs - 0.09 + i * 0.09, y - 0.15 + j * 0.1, z + 0.1), (xs - 0.09 + i * 0.09, y - 0.15 + j * 0.1, z + 0.22), 0.03, 8))
            y += w_ + rg.uniform(0.03, 0.12)
    fl.mesh_object("H5PrepRun", [(body, ctr), (steel, top + shelves + sup + trol + pans), (dark, sink), (white, pl), (card, boxes), (film, films), (glass, racks)], bevel=False)
    _light("ir_h5_prep_0", "AREA", ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, 3.4), 400, (1.0, 0.95, 0.85), sx=1.5, sy=6.0)
    stats["h5_kitchen"] = 1


def _bed_slot(f, lo, hi, L=2.1, W=1.5):
    """First free L x W slot with its head to a wall, clear of every object and 0.9 m from the doors: (wall, rect) or None."""
    obs = []
    for o in bpy.data.objects:
        if o.type != "MESH" or o is f or o.name.endswith((".floor", ".ceiling", ".wall", ".exterior")) or o.name.startswith(("Baseboard", "H5")) or ("/" in o.name and "(" not in o.name and "." not in o.name):      # not the room-shell mesh 'bedroom_0/8'
            continue
        b0, b1 = _bb(o)
        if b1[2] > 0.25 and b0[2] < 2.0 and b1[0] > lo[0] and b0[0] < hi[0] and b1[1] > lo[1] and b0[1] < hi[1]:
            pad = 0.3 if o.name.startswith(("LiteDoor", "GlassPanelDoor", "PanelDoor", "door", "DoorCasing")) else 0.05      # r6: 0.9 m left bedroom_0/8 (two doors) no slot; the door.* bbox already spans the swing
            obs.append((b0[0] - pad, b1[0] + pad, b0[1] - pad, b1[1] + pad))
    for wall in ("N", "S", "W", "E"):
        along = (lo[0], hi[0]) if wall in ("N", "S") else (lo[1], hi[1]); u = along[0] + 0.5 + W / 2
        while u < along[1] - 0.5 - W / 2:
            r = {"S": (u - W / 2, u + W / 2, lo[1] + 0.02, lo[1] + 0.02 + L), "N": (u - W / 2, u + W / 2, hi[1] - 0.02 - L, hi[1] - 0.02),
                 "W": (lo[0] + 0.02, lo[0] + 0.02 + L, u - W / 2, u + W / 2), "E": (hi[0] - 0.02 - L, hi[0] - 0.02, u - W / 2, u + W / 2)}[wall]
            if r[0] >= lo[0] and r[1] <= hi[0] and r[2] >= lo[1] and r[3] <= hi[1] and not any(r[0] < q[1] and q[0] < r[1] and r[2] < q[3] and q[2] < r[3] for q in obs):
                return wall, r
            u += 0.1
    return None


def _bed_spare(stats):
    """FUN-01: a guest room whose layout bed was refused (door keep-outs in a narrow room) gets a plain double bed, head to the wall, in the first free slot away from the doors; if none, the room's sofa / armchair make way."""
    fl = _fl(); frame = _flat("ir_h5_bedframe", (0.35, 0.3, 0.26), 0.6); mat = _flat("ir_h5_mattress", (0.95, 0.95, 0.93), 0.9); duv = _flat("ir_h5_duvet", (0.8, 0.8, 0.78), 0.9); head = _flat("ir_h5_headboard", (0.5, 0.48, 0.46), 0.8); n = 0; L, W = 2.1, 1.5
    for f in list(bpy.data.objects):
        if not (f.type == "MESH" and f.name.startswith("bedroom_0/") and f.name.endswith(".floor")):
            continue
        lo, hi = _fbox(f)
        if any(o.type == "MESH" and o.name.startswith("SoftBedFactory") and _in_room(o, lo, hi) for o in bpy.data.objects):
            continue
        best = _bed_slot(f, lo, hi, L, W)
        if best is None:
            for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("AboSofa", "AccentArmchair", "AboArmchair", "AboCoffeeTable", "CoffeeTable")) and _in_room(o, lo, hi)]:
                bpy.data.objects.remove(o, do_unlink=True)
            best = _bed_slot(f, lo, hi, L, W)
        if best is None:
            W = 1.4; best = _bed_slot(f, lo, hi, L, W)
        if best is None:
            stats.setdefault("h5_spare_bed_fail", []).append(f.name[:-6]); continue
        wall, r = best; cx, cy = (r[0] + r[1]) / 2, (r[2] + r[3]) / 2
        hx = {"W": (-1, 0), "E": (1, 0), "S": (0, -1), "N": (0, 1)}[wall]
        def at(a, b, z, sa, sb, sz):                      # a along the bed length (head = +), b across
            px, py = cx + hx[0] * a - hx[1] * b, cy + hx[1] * a + hx[0] * b
            return ("box", px, py, z, *((sa, sb) if hx[0] else (sb, sa)), sz)
        rb_ = ra.abo("bed", 7 + n, cx, cy, lo[2], math.atan2(-hx[1], -hx[0]), fit=(W + 0.15, L + 0.1, 1.4))      # a real ABO bed (audit H5-1); the box bed only as the fallback
        if rb_ is not None:
            rb_.name = f"H5SpareBed({f.name[:-6]})"; n += 1; continue
        fl.mesh_object(f"H5SpareBed({f.name[:-6]})", [(frame, [at(0, 0, 0.2, L, W, 0.25)]), (mat, [at(-0.03, 0, 0.4, L - 0.1, W - 0.1, 0.2)]), (duv, [at(-0.35, 0, 0.52, L * 0.55, W - 0.05, 0.06)]),
                                                     (head, [at(L / 2 - 0.04, 0, 0.8, 0.08, W + 0.2, 1.1)]), (mat, [at(L / 2 - 0.3, -0.35, 0.55, 0.3, 0.5, 0.12), at(L / 2 - 0.3, 0.35, 0.55, 0.3, 0.5, 0.12)])], bevel=False); n += 1
    stats["h5_spare_beds"] = n


# ---------------------------------------------------------------- realism batch 1 (H5-REAL-1 / H5-REAL-2) -----------------------------------------------------------------------

def _veined(name, rgb, vein_rgb, size, grout, rough, vein_scale=4.0):
    """Polished stone tile: lux_shell._tile (square cells, thin grout) + a distorted-noise vein multiply at 5-30 cm."""
    import lux_shell
    m = lux_shell._tile(name, rgb, rough, size=size, grout=grout, mrgb=tuple(c * 0.8 for c in rgb))
    if m.get("h5_vein"):
        return m
    nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    src = b.inputs["Base Color"].links[0].from_socket
    tc = N.new("ShaderNodeTexCoord"); no = N.new("ShaderNodeTexNoise"); no.inputs["Scale"].default_value = vein_scale; no.inputs["Detail"].default_value = 10.0; no.inputs["Distortion"].default_value = 4.0
    L.new(tc.outputs["Object"], no.inputs["Vector"])
    mr = N.new("ShaderNodeMapRange"); mr.inputs["From Min"].default_value = 0.46; mr.inputs["From Max"].default_value = 0.54; L.new(no.outputs["Fac"], mr.inputs["Value"])
    mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.inputs["B"].default_value = (*vein_rgb, 1)
    inv = N.new("ShaderNodeMath"); inv.operation = "PINGPONG"; inv.inputs[1].default_value = 0.5; L.new(mr.outputs["Result"], inv.inputs[0])     # thin dark lines where the noise crosses 0.5
    one = N.new("ShaderNodeMath"); one.operation = "SUBTRACT"; one.inputs[1].default_value = 0.42; L.new(inv.outputs[0], one.inputs[0])     # r11: was 0.5 - pp (vein colour everywhere = pale terrazzo); now only pp > 0.42
    pw = N.new("ShaderNodeMath"); pw.operation = "MULTIPLY"; pw.inputs[1].default_value = 12.0; pw.use_clamp = True; L.new(one.outputs[0], pw.inputs[0])
    L.new(pw.outputs[0], mx.inputs["Factor"]); L.new(src, mx.inputs["A"]); L.new(mx.outputs["Result"], b.inputs["Base Color"])
    m["h5_vein"] = 1
    return m


def _plank(name="ir_h5_oak_plank"):
    """Light oak plank floor: 18 cm x 1.2 m staggered boards, per-board tint, fine grain."""
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    rgb = (0.66, 0.5, 0.34)
    m = _flat(name, rgb, 0.42); nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); br = N.new("ShaderNodeTexBrick"); L.new(tc.outputs["Object"], br.inputs["Vector"])
    br.offset = 0.5; br.inputs["Scale"].default_value = 1.0; br.inputs["Brick Width"].default_value = 1.2; br.inputs["Row Height"].default_value = 0.18; br.inputs["Mortar Size"].default_value = 0.002; br.inputs["Bias"].default_value = 0.0
    br.inputs["Color1"].default_value = (*rgb, 1); br.inputs["Color2"].default_value = (0.58, 0.42, 0.27, 1); br.inputs["Mortar"].default_value = (0.3, 0.22, 0.14, 1)
    wv = N.new("ShaderNodeTexWave"); wv.wave_type = "BANDS"; wv.bands_direction = "X"; wv.inputs["Scale"].default_value = 30.0; wv.inputs["Distortion"].default_value = 6.0; wv.inputs["Detail"].default_value = 3.0
    L.new(tc.outputs["Object"], wv.inputs["Vector"])
    mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.blend_type = "MULTIPLY"; mx.inputs["Factor"].default_value = 0.18; mx.inputs["B"].default_value = (0.55, 0.45, 0.35, 1)
    L.new(br.outputs["Color"], mx.inputs["A"]); L.new(wv.outputs["Fac"], mx.inputs["Factor"]); L.new(mx.outputs["Result"], b.inputs["Base Color"])
    return m


def _plant_niche(pr, mats, axis, line, side, u, zc=1.55, w=0.8, h=1.6, rng=None):
    """A framed 3D plant niche proud of the wall (15 cm): dark back, bronze frame, moss + fern leaf boxes, warm LED strip on top. Appends prims to pr[mat]."""
    rng = rng or random.Random(int(u * 100))
    def P(a, d, z, sa, sd, sz, yaw=0.0):                    # a along the wall, d out of the wall (towards the room)
        if axis == 0:
            return ("box", a, line + side * d, z, sa, sd, sz, yaw)
        return ("box", line + side * d, a, z, sd, sa, sz, yaw)
    pr[mats["back"]].append(P(u, 0.02, zc, w, 0.04, h))
    for a_, sa in ((u - w / 2 - 0.025, 0.05), (u + w / 2 + 0.025, 0.05)):
        pr[mats["frame"]].append(P(a_, 0.08, zc, sa, 0.16, h + 0.1))
    for z_ in (zc - h / 2 - 0.025, zc + h / 2 + 0.025):
        pr[mats["frame"]].append(P(u, 0.08, z_, w + 0.1, 0.16, 0.05))
    pr[mats["led"]].append(P(u, 0.1, zc + h / 2 - 0.02, w - 0.04, 0.02, 0.015))
    if axis is not None and getattr(_plant_niche, "real", True):   # r8 review: real potted plants on two niche shelves instead of leaf boxes
        ok_ = 0
        for zs_ in (zc - h / 2 + 0.06, zc + 0.02):
            pr[mats["frame"]].append(P(u, 0.08, zs_ - 0.012, w - 0.02, 0.14, 0.02))
            for da in (-w / 4, w / 4):
                x_, y_ = ((u + da, line + side * 0.08) if axis == 0 else (line + side * 0.08, u + da))
                ok_ += ra.abo("smallplant", int(u * 37 + da * 11 + zs_ * 5) & 0xffff, x_, y_, zs_, rng.uniform(0, 6.28), fit=(0.3, 0.13, min(0.42, h / 2 - 0.1))) is not None
        if ok_:
            return
    for _ in range(140):                                     # moss carpet + fern fronds
        a_ = u + rng.uniform(-w / 2 + 0.03, w / 2 - 0.03); z_ = zc + rng.uniform(-h / 2 + 0.04, h / 2 - 0.06); s_ = rng.uniform(0.04, 0.11)
        pr[rng.choice((mats["leaf"], mats["leaf2"], mats["moss"]))].append(P(a_, rng.uniform(0.05, 0.12), z_, s_, rng.uniform(0.02, 0.06), s_ * rng.uniform(0.3, 0.8), rng.uniform(-0.8, 0.8)))


def _niche_mats():
    return {"back": _flat("ir_h5_niche_back", (0.05, 0.06, 0.04), 0.9), "frame": _flat("ir_h5_bronze", (0.36, 0.24, 0.14), 0.3, 1.0), "led": _emit("ir_h5_led", (1.0, 0.82, 0.55), 6.0),
            "leaf": _flat("ir_h5_leaf", (0.12, 0.3, 0.08), 0.6), "leaf2": _flat("ir_h5_leaf2", (0.2, 0.42, 0.12), 0.55), "moss": _flat("ir_h5_moss", (0.18, 0.28, 0.06), 0.95)}


def _emit_mesh(name, pr):
    pr = {m: p for m, p in pr.items() if p}
    if pr:
        _fl().mesh_object(name, list(pr.items()), bevel=False)
        _soft(bpy.data.objects.get(name))


def _soft(o, w=0.012):
    """Rounded edges (3 segments) on a soft / furniture-scale prim object: no razor box edges (user 10-25: no boxy modelling)."""
    if o is not None and o.type == "MESH" and not o.modifiers.get("ir_soft"):
        md = o.modifiers.new("ir_soft", "BEVEL"); md.width = w; md.segments = 3; md.limit_method = "ANGLE"; md.harden_normals = False


def _rm_in(lo, hi, prefixes, zmin=-9.0, lights=False):
    n = 0
    for o in list(bpy.data.objects):
        if (o.type == "MESH" and o.name.startswith(prefixes)) or (lights and o.type == "LIGHT" and not o.name.startswith("ir_")):
            b0, b1 = _bb(o); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
            if lo[0] < cx < hi[0] and lo[1] < cy < hi[1] and b1[2] > zmin:
                bpy.data.objects.remove(o, do_unlink=True); n += 1
    return n


def _bed_frame(o):
    """(centre x, y, head unit dir (hx, hy), length along head, width, mattress top z) of a bed: the head is where its highest vertices sit."""
    b0, b1 = _bb(o); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
    vs = [o.matrix_world @ v.co for v in o.data.vertices]; zt = max(v.z for v in vs)
    hv = [v for v in vs if v.z > zt - 0.15]; hx_, hy_ = sum(v.x for v in hv) / len(hv) - cx, sum(v.y for v in hv) / len(hv) - cy
    h = ((1 if hx_ > 0 else -1), 0) if abs(hx_) > abs(hy_) else (0, (1 if hy_ > 0 else -1))
    L, W = (b1[0] - b0[0], b1[1] - b0[1]) if h[0] else (b1[1] - b0[1], b1[0] - b0[0])
    foot = [v.z for v in vs if ((v.x - cx) * h[0] + (v.y - cy) * h[1]) < -L * 0.2]
    return cx, cy, h, L, W, (max(foot) if foot else 0.6)


def _rooms_dress(stats):
    """Guest rooms: oak plank floor, cream walls, stepped cove ceiling + downlights (tracks / domes gone), rug, dressed bed, oak nightstands + lamps, headboard wall, TV + oak credenza, 2 prints."""
    fl = _fl(); floor = _plank(); wallm = _noise_mix("ir_h5_room_wall", (0.88, 0.84, 0.76), (0.84, 0.8, 0.72), 3.0, rough=0.85)
    oak = _wood("ir_h5_oak", (0.62, 0.45, 0.28)); fab = _flat("ir_h5_fabric_panel", (0.62, 0.58, 0.52), 0.92); duv = _flat("ir_h5_duvet_w", (0.95, 0.94, 0.92), 0.95)
    pil = _flat("ir_h5_pillow", (0.97, 0.97, 0.96), 0.95); knit = _flat("ir_h5_knit", (0.45, 0.43, 0.42), 0.97); rugm = _noise_mix("ir_h5_room_rug", (0.8, 0.74, 0.64), (0.72, 0.66, 0.56), 40.0, rough=0.98)
    shade = _emit("ir_h5_shade", (1.0, 0.86, 0.66), 3.0); cer = _flat("ir_h5_ceramic", (0.86, 0.84, 0.8), 0.3); cream = _flat("ir_h5_ceil", (0.9, 0.88, 0.84), 0.6)
    cove = _emit("ir_h5_cove", (1.0, 0.78, 0.5), 3.0); disc = _emit("ir_h5_dl", (1.0, 0.86, 0.66), 12.0); tvm = _flat("ir_h5_tv", (0.01, 0.01, 0.012), 0.08); blk = _flat("ir_h5_black", (0.02, 0.02, 0.02), 0.4)
    mat_w = _flat("ir_h5_mat", (0.95, 0.94, 0.9), 0.8)
    arts = [(0.55, 0.42, 0.3), (0.3, 0.42, 0.5), (0.5, 0.52, 0.4), (0.62, 0.36, 0.3), (0.36, 0.38, 0.46)]
    throws = [(0.45, 0.43, 0.42), (0.36, 0.3, 0.26), (0.32, 0.38, 0.44), (0.5, 0.4, 0.3), (0.4, 0.44, 0.36)]
    n = nb = 0
    for f in sorted([o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("bedroom_0/") and o.name.endswith(".floor")], key=lambda o: o.name):
        rn = f.name[:-6]; lo, hi = _fbox(f); k = int(rn.split("/")[1]); rg = random.Random(k)
        hb_ = bpy.data.objects.get(f"H5Headboard({rn})")
        if hb_ is not None:
            bpy.data.objects.remove(hb_, do_unlink=True)
        for sl in f.material_slots:
            sl.material = floor
        w = bpy.data.objects.get(f"{rn}.wall")
        if w is not None:
            for sl in w.material_slots:
                sl.material = wallm
        _rm_in(lo, hi, ("TrackRailFactory", "TrackSpotFactory", "AboCeilingFixtureFactory", "SoffitFactory", "CeilingLightFactory"))
        _rm_in((lo[0], lo[1]), (hi[0], hi[1]), (), lights=True)
        pr = {m: [] for m in (cream, cove, disc, oak, fab, duv, pil, knit, rugm, shade, cer, tvm, blk, mat_w)}
        # stepped ceiling: 45 cm perimeter soffit 15 cm deep, cove strip on its inner edge, 4 downlights in it
        x0, x1, y0, y1 = lo[0], hi[0], lo[1], hi[1]; b_ = 0.45; zb = ZC - 0.15
        for cx_, cy_, sx_, sy_ in (((x0 + x1) / 2, y0 + b_ / 2, x1 - x0, b_), ((x0 + x1) / 2, y1 - b_ / 2, x1 - x0, b_), (x0 + b_ / 2, (y0 + y1) / 2, b_, y1 - y0 - 2 * b_), (x1 - b_ / 2, (y0 + y1) / 2, b_, y1 - y0 - 2 * b_)):
            pr[cream].append(("box", cx_, cy_, zb + 0.075, sx_, sy_, 0.15))
        for cx_, cy_, sx_, sy_ in (((x0 + x1) / 2, y0 + b_ + 0.015, x1 - x0 - 2 * b_, 0.03), ((x0 + x1) / 2, y1 - b_ - 0.015, x1 - x0 - 2 * b_, 0.03), (x0 + b_ + 0.015, (y0 + y1) / 2, 0.03, y1 - y0 - 2 * b_), (x1 - b_ - 0.015, (y0 + y1) / 2, 0.03, y1 - y0 - 2 * b_)):
            pr[cove].append(("box", cx_, cy_, zb + 0.03, sx_, sy_, 0.02))
        for t in range(6):
            px, py = (x0 + b_ / 2, x1 - b_ / 2)[t % 2], y0 + (y1 - y0) * (0.2 + 0.3 * (t // 2))
            pr[disc].append(("cyl", (px, py, zb - 0.004), (px, py, zb + 0.001), 0.045, 16))
            ld = _light(f"ir_h5_rdl_{rn}_{t}", "SPOT", (px, py, zb - 0.01), 260, (1.0, 0.78, 0.52)); ld.data.spot_size = math.radians(70)
        beds = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("SoftBedFactory", "H5SpareBed")) and _in_room(o, lo, hi)]
        if beds:
            bo = beds[0]; cx, cy, h, L, W, zt = _bed_frame(bo); nb += 1
            def at(a, b, z, sa, sb, sz, yaw=0.0):
                px, py = cx + h[0] * a - h[1] * b, cy + h[1] * a + h[0] * b
                return ("box", px, py, z, *((sa, sb) if h[0] else (sb, sa)), sz, yaw)
            def cyl(a, b, z0, z1, r):
                px, py = cx + h[0] * a - h[1] * b, cy + h[1] * a + h[0] * b
                return ("cyl", (px, py, z0), (px, py, z1), r, 20)
            zt = max(zt, 0.45)
            import h2_ref                                          # r8 review: a soft draped duvet (cloth mesh hanging over both sides, folds) + rounded pillows, not boxes
            a0_, a1_ = -L / 2 - 0.04, L / 2 - 0.55
            ex = sorted((cx + h[0] * a0_, cx + h[0] * a1_)) if h[0] else (cx - W / 2, cx + W / 2)
            ey = (cy - W / 2, cy + W / 2) if h[0] else sorted((cy + h[1] * a0_, cy + h[1] * a1_))
            h2_ref._drape(f"H5Duvet({rn})", duv, ex[0], ex[1], ey[0], ey[1], zt + 0.1, 0.36, bool(h[0]), thick=0.06, seed=k)
            pr[duv].append(at(L * 0.27 - 0.12, 0, zt + 0.12, 0.2, W + 0.04, 0.05))          # the turned-down fold
            pass                                                   # r8 test: the flat knit runner z-fought the draped duvet (holes); the guests part adds real throws
            for j_, b in enumerate((-W / 4, W / 4)):
                for q_, (a_, z_, sh_) in enumerate(((L / 2 - 0.28, zt + 0.2, 0.17), (L / 2 - 0.46, zt + 0.16, 0.15))):
                    px_, py_ = cx + h[0] * a_ - h[1] * b, cy + h[1] * a_ + h[0] * b
                    sx_, sy_ = ((0.2, W / 2 - 0.08) if h[0] else (W / 2 - 0.08, 0.2))
                    h2_ref._soft(f"H5Pillow({rn}|{j_}{q_})", pil, px_, py_, z_, sx_, sy_, sh_, yaw=0.0, bevel=0.07, bump=0.008, seed=k * 4 + j_ * 2 + q_)
            tc = throws[k % len(throws)]; cm = _flat(f"ir_h5_cushion_{k % len(throws)}", tc, 0.9)
            def pt(a, b):
                return cx + h[0] * a - h[1] * b, cy + h[1] * a + h[0] * b
            # r15 layered bedding (r14 #6: flat white duvet + two cushions): 2 upright euro pillows against the headboard, a wide soft throw in the room colour across the foot, the turned-down band stays
            eur = _flat("ir_h5_euro", (0.93, 0.92, 0.9), 0.95); thr_m = _flat(f"ir_h5_throw_{k % len(throws)}", tc, 0.97)
            for j_, b_e in enumerate((-W / 4, W / 4)):
                px_e, py_e = pt(L / 2 - 0.2, b_e)
                h2_ref._soft(f"H5Euro({rn}|{j_})", eur, px_e, py_e, zt + 0.34, *((0.17, 0.58) if h[0] else (0.58, 0.17)), 0.56, yaw=0.0, bevel=0.08, bump=0.008, seed=k * 11 + j_)
            fa0, fa1 = -L / 2 - 0.02, -L / 2 + 0.58
            fx = sorted((cx + h[0] * fa0, cx + h[0] * fa1)) if h[0] else (cx - W / 2 - 0.03, cx + W / 2 + 0.03)
            fy = (cy - W / 2 - 0.03, cy + W / 2 + 0.03) if h[0] else sorted((cy + h[1] * fa0, cy + h[1] * fa1))
            h2_ref._drape(f"H5FootThrow({rn})", thr_m, fx[0], fx[1], fy[0], fy[1], zt + 0.16, 0.42, bool(h[0]), thick=0.05, seed=k + 31)
            yfoot = math.atan2(-h[1], -h[0])                      # real models face the foot of the bed
            for j_, b_ in enumerate((-0.2, 0.2)):                 # accent cushions: ABO throw pillows
                if ra.abo("pillow", k * 7 + j_, *pt(L / 2 - 0.68, b_), zt + 0.02, yfoot + 0.15 * (1 if b_ > 0 else -1), fit=(0.48, 0.2, 0.42)) is None:
                    pr.setdefault(cm, []).append(at(L / 2 - 0.68, b_, zt + 0.15, 0.14, 0.4, 0.34))
            if ra.abo("bigrug", k, *pt(-0.45, 0), 0.132, yfoot, fit=(3.2, 2.4, 0.05)) is None:
                pr[rugm].append(at(-0.45, 0, 0.138, 3.2, 2.4, 0.012))
            _rm_in(lo, hi, ("AboNightstandFactory", "AboTableLampFactory"))
            for s_ in (-1, 1):
                b = s_ * (W / 2 + 0.3)
                ns_ = ra.abo("nightstand", k * 3 + (s_ > 0), *pt(L / 2 - 0.3, b), 0.13, yfoot, fit=(0.5, 0.45, 0.62))
                if ns_ is None:
                    pr[oak] += [at(L / 2 - 0.3, b, 0.4, 0.42, 0.46, 0.5)]
                ztop_ = ra.top(ns_) if ns_ is not None else 0.65
                if ra.abo("tablelamp", k * 5 + (s_ > 0), *pt(L / 2 - 0.3, b), ztop_, yfoot, fit=(0.4, 0.4, 0.55)) is None:
                    pr[cer].append(cyl(L / 2 - 0.3, b, 0.65, 0.95, 0.06)); pr[shade].append(cyl(L / 2 - 0.3, b, 0.95, 1.18, 0.16))
                px, py = cx + h[0] * (L / 2 - 0.3) - h[1] * b, cy + h[1] * (L / 2 - 0.3) + h[0] * b
                _light(f"ir_h5_lamp_{rn}_{s_}", "POINT", (px, py, 1.05), 160, (1.0, 0.75, 0.48), r=0.1)
            # headboard wall: full-height panelling if the head is at a room wall, else a 1.4 m oak-clad spine wall 2.6 m wide
            hp = (cx + h[0] * L / 2, cy + h[1] * L / 2); dwall = {(1, 0): hi[0] - hp[0], (-1, 0): hp[0] - lo[0], (0, 1): hi[1] - hp[1], (0, -1): hp[1] - lo[1]}[h]
            if dwall < 0.6:
                a_w = L / 2 + dwall - 0.05; ztop = ZC - 0.16; wd = W + 1.6
            else:
                a_w = L / 2 + 0.07; ztop = 1.4; wd = W + 0.9
                _rm_in(lo, hi, ("AboArmchairFactory",), zmin=9.0)
            pr[oak].append(at(a_w, 0, ztop / 2 + 0.065, 0.1, wd, ztop - 0.13))
            for i in range(int(wd / 0.12)):                       # vertical oak fins on the bed side
                pr[oak].append(at(a_w - 0.06, -wd / 2 + 0.06 + i * 0.12, ztop / 2 + 0.065, 0.03, 0.03, ztop - 0.13))
            pr[fab] += [at(a_w - 0.09, 0, min(ztop, 1.3) / 2 + 0.35, 0.05, W + 0.3, min(ztop, 1.3) - 0.4)]
            for j in range(5):                                    # channel tufting
                pr[fab].append(at(a_w - 0.115, 0, 0.6 + j * 0.15 * (min(ztop, 1.3) - 0.4) / 0.75, 0.02, W + 0.28, 0.1))
            # r15 #4: a large framed print centred over the headboard with a brass picture light (the side walls stay free for bedwalls)
            ax_, ay_ = pt(a_w - 0.17, 0)
            if ra.abo("wallart", 700 + k, ax_, ay_, 1.42, yfoot, fit=(min(1.3, W + 0.4), 0.06, 0.85)) is not None:
                brs = _flat("ir_h5_brass_w", (0.74, 0.55, 0.24), 0.3, 1.0)
                pr.setdefault(brs, []).append(("box", *pt(a_w - 0.2, 0), 2.33, *((0.05, 0.5) if h[0] else (0.5, 0.05)), 0.03))
                _light(f"ir_h5_piclight_{rn}", "POINT", (*pt(a_w - 0.3, 0), 2.28), 150, (1.0, 0.8, 0.55), r=0.05)
        # TV + oak credenza replace the blank board (MenuBoard / MediaWall), 2 framed prints opposite
        boards = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("MenuBoardFactory", "MediaWallFactory", "BedroomMediaFactory")) and _in_room(o, lo, hi)]
        for bo_ in boards:
            b0, b1 = _bb(bo_); bpy.data.objects.remove(bo_, do_unlink=True)
            bx, by = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
            d = {"W": bx - lo[0], "E": hi[0] - bx, "S": by - lo[1], "N": hi[1] - by}; wn = min(d, key=d.get)
            ax = 1 if wn in ("W", "E") else 0; line = {"W": lo[0], "E": hi[0], "S": lo[1], "N": hi[1]}[wn]; sd = 1 if wn in ("W", "S") else -1
            u = by if ax else bx; ulo, uhi = (lo[1], hi[1]) if ax else (lo[0], hi[0]); u = min(max(u, ulo + 1.3), uhi - 1.3); cl = min(2.4, uhi - ulo - 0.4)
            def wb(uu, dd, z, su, sd_, sz):
                return ("box", line + sd * dd, uu, z, sd_, su, sz) if ax else ("box", uu, line + sd * dd, z, su, sd_, sz)
            yin = math.atan2(0, sd) if ax else math.atan2(sd, 0)        # facing into the room
            px_c, py_c = ((line + sd * 0.26, u) if ax else (u, line + sd * 0.26))
            cr_ = ra.abo("credenza", k + 1, px_c, py_c, 0.13, yin, fit=(cl, 0.5, 0.7))      # audit H5-5: a real media console + TV, boxes only as the fallback
            if cr_ is None:
                pr[oak] += [wb(u, 0.26, 0.38, cl, 0.45, 0.5)]
            px_t, py_t = ((line + sd * 0.06, u) if ax else (u, line + sd * 0.06))
            tv_ = ra.abo("tv", k + 2, px_t, py_t, 0.95, yin, fit=(1.25, 0.12, 0.8))
            if tv_ is None:
                pr[blk] += [wb(u, 0.03, 1.3, 1.25, 0.04, 0.74)]; pr[tvm] += [wb(u, 0.052, 1.3, 1.21, 0.004, 0.70)]
            opp = {"W": hi[0], "E": lo[0], "S": hi[1], "N": lo[1]}[wn]; so = -sd
            ac = arts[k % len(arts)]; am = _flat(f"ir_h5_art_{k % len(arts)}", ac, 0.7)
            wins = [_bb(o) for o in bpy.data.objects if o.type == "MESH" and ("Window" in o.name or o.name.startswith("window")) and abs(((_bb(o)[0][0] + _bb(o)[1][0]) / 2 if ax else (_bb(o)[0][1] + _bb(o)[1][1]) / 2) - opp) < 0.5]
            for du in (-0.45, 0.45):
                if any((w0[1] if ax else w0[0]) - 0.35 < u + du < (w1[1] if ax else w1[0]) + 0.35 for w0, w1 in wins):
                    continue                                      # not over a window (r8 test: prints hung on the glass in 0-14)
                px_a, py_a = ((opp + so * 0.03, u + du) if ax else (u + du, opp + so * 0.03))
                if ra.abo("wallart", k * 3 + int(du > 0), px_a, py_a, 1.18, (math.atan2(0, so) if ax else math.atan2(so, 0)), fit=(0.7, 0.06, 0.9)) is not None:
                    continue                                      # audit H5-6: real framed art
                for mm, dd, su, sz in ((blk, 0.015, 0.64, 0.84), (mat_w, 0.032, 0.56, 0.76), (am, 0.035, 0.36, 0.52)):
                    pr.setdefault(mm, []).append(("box", opp + so * dd, u + du, 1.6, 0.03, su, sz) if ax else ("box", u + du, opp + so * dd, 1.6, su, 0.03, sz))
        _emit_mesh(f"H5RoomDress({rn})", pr); n += 1
    stats["h5_rooms_dress"] = {"rooms": n, "beds_dressed": nb}


def _lounge_groups(stats):
    """Sky lounge: the bistro tables / bench / mixed sofas go; 3 seating groups (curved bouclé sofa, 2 barrel chairs, Ø1.1 dark coffee table, Ø3 m rug, cushions, tabletop decor),
    champagne-bronze columns, polished 800 x 800 cream marble."""
    lo, hi = _room(LOUNGE)
    if lo is None:
        return
    fl = _fl()
    rm = _rm_in(lo, hi, ("AboArmchairFactory", "AboCoffeeFactory", "AboRugFactory", "AboSofaFactory", "CafeTableFactory", "CafeChairFactory", "AboCafechairFactory", "BreakTableFactory", "ChairFactory", "BenchFactory", "AboBenchFactory", "AboCoffeetableFactory", "H5LoungeRug", "TableDiningFactory"))
    _set_floor(LOUNGE, _veined("ir_h5_marble_800", (0.86, 0.81, 0.72), (0.62, 0.55, 0.47), 0.8, 0.0015, 0.09))
    col = bpy.data.objects.get("H5LoungeColumns")
    if col is not None:
        cm = _flat("ir_h5_champagne", (0.62, 0.5, 0.37), 0.35, 1.0); col.data.materials[0] = cm
    bou = _noise_mix("ir_h5_boucle", (0.6, 0.58, 0.55), (0.52, 0.5, 0.47), 60.0, rough=0.97); dark = _flat("ir_h5_darkwood", (0.08, 0.06, 0.05), 0.25)
    rug = _noise_mix("ir_h5_lounge_rug", (0.82, 0.78, 0.7), (0.76, 0.72, 0.64), 50.0, rough=0.98); cush = [_flat("ir_h5_cush_rust", (0.55, 0.3, 0.18), 0.9), _flat("ir_h5_cush_navy", (0.12, 0.16, 0.28), 0.9), _flat("ir_h5_cush_cream", (0.9, 0.86, 0.78), 0.9)]
    deco = _flat("ir_h5_deco", (0.9, 0.88, 0.82), 0.3); green = _flat("ir_h5_leaf", (0.12, 0.3, 0.08), 0.6)
    pr = {m: [] for m in [bou, dark, rug, deco, green] + cush}
    groups = [(2.6, 11.9, 0.0), (2.6, 18.1, 0.0), (8.2, 15.0, math.pi)]          # facing the room (+x) at the glass, the third faces the glass
    for gi, (gx, gy, rot) in enumerate(groups):
        fx, fy = math.cos(rot), math.sin(rot)
        real_ = ra.abo("loungesofa", 11 + gi, gx - fx * 1.25, gy - fy * 1.25, 0.13, rot, fit=(3.0, 1.1, 0.95))      # real models first (user 10-25: no box modelling); prims only as the fallback
        if real_ is not None:
            ra.abo("bigrug", 21 + gi, gx - fx * 0.3, gy - fy * 0.3, 0.13, rot, fit=(3.4, 3.0, 0.05))
            ra.abo("roundtable", 31 + gi, gx, gy, 0.14, 0.0, fit=(1.1, 1.1, 0.5)) or ra.abo("coffee", 31 + gi, gx, gy, 0.14, rot, fit=(1.2, 0.8, 0.5))
            for sgn in (-1, 1):
                a = rot + sgn * 0.75; px, py = gx + math.cos(a) * 1.25, gy + math.sin(a) * 1.25
                ra.abo("barrel", 41 + gi * 2 + (sgn > 0), px, py, 0.13, a + math.pi, fit=(0.9, 0.9, 0.95))
            ra.lib("VaseFactory", 51 + gi, gx + 0.2, gy - 0.1, 0.52, 0.0, 0.6)
            ra.abo("smallplant", 61 + gi, gx - 0.2, gy + 0.15, 0.52, 0.0, fit=(0.35, 0.35, 0.4))
            continue
        pr[rug].append(("cyl", (gx, gy, 0.132), (gx, gy, 0.142), 1.5, 48))
        pr[dark] += [("cyl", (gx, gy, 0.14), (gx, gy, 0.5), 0.55, 40), ("cyl", (gx, gy, 0.14), (gx, gy, 0.2), 0.5, 40)]
        pr[deco] += [("box", gx - 0.15, gy + 0.1, 0.53, 0.26, 0.2, 0.06, 0.3), ("cyl", (gx + 0.2, gy - 0.1, 0.5), (gx + 0.2, gy - 0.1, 0.6), 0.09, 16)]
        pr[green].append(("cyl", (gx + 0.2, gy - 0.1, 0.6), (gx + 0.2, gy - 0.1, 0.7), 0.11, 12))
        R = 1.25; segs = 9; a0, a1 = rot + math.pi - 1.1, rot + math.pi + 1.1          # curved sofa behind the table (away from the facing direction)
        for i in range(segs):
            a = a0 + (a1 - a0) * (i + 0.5) / segs; px, py = gx + math.cos(a) * R, gy + math.sin(a) * R; ln = 2 * R * math.sin((a1 - a0) / segs / 2) + 0.03; yaw = a + math.pi / 2
            pr[bou] += [("box", px, py, 0.3, ln, 0.7, 0.3, yaw), ("box", gx + math.cos(a) * (R + 0.3), gy + math.sin(a) * (R + 0.3), 0.6, ln, 0.16, 0.65, yaw)]
        for j, a in enumerate((a0 + 0.35, (a0 + a1) / 2, a1 - 0.35)):
            pr[cush[(gi + j) % 3]].append(("box", gx + math.cos(a) * (R + 0.12), gy + math.sin(a) * (R + 0.12), 0.6, 0.42, 0.14, 0.4, a + math.pi / 2))
        for sgn in (-1, 1):                                    # 2 barrel chairs facing the sofa
            a = rot + sgn * 0.75; px, py = gx + math.cos(a) * 1.2, gy + math.sin(a) * 1.2
            pr[bou].append(("cyl", (px, py, 0.14), (px, py, 0.45), 0.38, 24))
            for t in range(7):
                aa = a + math.pi / 2 + t * math.pi / 6 - 0.0; qx, qy = px + math.cos(aa) * 0.34, py + math.sin(aa) * 0.34
                pr[bou].append(("box", qx, qy, 0.6, 0.2, 0.1, 0.32, aa + math.pi / 2))
    _emit_mesh("H5LoungeGroups", pr)
    stats["h5_lounge_groups"] = {"removed": rm, "groups": len(groups)}; stats["h5_real_assets"] = {k_: v_ for k_, v_ in ra.STATS.items()}


def _plain_metal(name, rgb, rough, aniso=0.0):
    """r13: smooth metal. _flat's surface-detail pass adds hairline streak bump + luminance drift that read as bark on the lift leaves; unlink those and set flat values (+ a little anisotropy for a brushed look)."""
    m = _flat(name, rgb, rough, 1.0)
    if not m.get("h5_plain"):
        b = m.node_tree.nodes["Principled BSDF"]
        for k in ("Base Color", "Normal", "Roughness"):
            for l_ in list(b.inputs[k].links):
                m.node_tree.links.remove(l_)
        b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = rough
        if aniso and "Anisotropic" in b.inputs:
            b.inputs["Anisotropic"].default_value = aniso
        m["h5_plain"] = 1
    return m


def _lifts(stats):
    """Lift hall: 4 recessed lift portals on the south wall: bronze frame with a 10 cm return, brushed-steel leaves with a centre seam, threshold, call panel + floor indicator; plant niches; fine marble."""
    lo, hi = _room(ELEV)
    if lo is None:
        return
    for nm in ("H5LiftDoors", "H5ElevNiches"):
        o = bpy.data.objects.get(nm)
        if o is not None:
            bpy.data.objects.remove(o, do_unlink=True)
    _set_floor(ELEV, _noise_mix("ir_h5_marble_fine", (0.84, 0.75, 0.64), (0.46, 0.32, 0.27), 6.5, rough=0.1, distort=2.5))
    br = _plain_metal("ir_h5_bronze", (0.5, 0.35, 0.2), 0.32); st = _plain_metal("ir_h5_lift_steel", (0.72, 0.7, 0.67), 0.3, 0.7); dk = _flat("ir_h5_black", (0.02, 0.02, 0.02), 0.4)
    if not st.get("h5_r14"):                       # r14: a full-metal leaf mirrored the warm walnut walls and read as brown 'bark'; the leaves are satin champagne-grey painted steel (dielectric), the frames darker bronze
        bs_ = st.node_tree.nodes["Principled BSDF"]; bs_.inputs["Base Color"].default_value = (0.68, 0.66, 0.62, 1); bs_.inputs["Metallic"].default_value = 0.0; bs_.inputs["Roughness"].default_value = 0.26
        bb_ = br.node_tree.nodes["Principled BSDF"]; bb_.inputs["Base Color"].default_value = (0.26, 0.17, 0.09, 1); bb_.inputs["Roughness"].default_value = 0.38
        st["h5_r14"] = 1
    btn = _emit("ir_h5_btn", (1.0, 0.85, 0.6), 4.0); ind = _emit("ir_h5_ind", (1.0, 0.45, 0.2), 3.0)
    pr = {m: [] for m in (br, st, dk, btn, ind)}
    ys = lo[1] + 0.12 + 0.04                                         # in front of the south wall panelling
    for x in (11.6, 14.0, 16.0, 18.4):
        W, H = 1.1, 2.4
        pr[st] += [("box", x - W / 4 - 0.002, ys + 0.03, 0.1 + H / 2, W / 2 - 0.004, 0.02, H), ("box", x + W / 4 + 0.002, ys + 0.03, 0.1 + H / 2, W / 2 - 0.004, 0.02, H)]
        pr[dk].append(("box", x, ys + 0.035, 0.1 + H / 2, 0.006, 0.02, H))          # centre seam
        for sx in (-1, 1):                                       # jambs: 10 cm face + 10 cm return
            pr[br] += [("box", x + sx * (W / 2 + 0.05), ys + 0.12, 0.1 + (H + 0.1) / 2, 0.1, 0.03, H + 0.1), ("box", x + sx * (W / 2 + 0.005), ys + 0.07, 0.1 + H / 2, 0.01, 0.1, H)]
        pr[br] += [("box", x, ys + 0.12, 0.1 + H + 0.075, W + 0.2, 0.03, 0.15), ("box", x, ys + 0.07, 0.1 + H + 0.005, W, 0.1, 0.01)]
        pr[st].append(("box", x, ys + 0.12, 0.112, W + 0.1, 0.16, 0.02))             # threshold
        pr[dk].append(("box", x, ys + 0.14, 0.1 + H + 0.3, 0.4, 0.02, 0.12)); pr[ind].append(("box", x, ys + 0.151, 0.1 + H + 0.3, 0.16, 0.004, 0.05))
        px = x + W / 2 + 0.28                                    # call panel beside the right jamb
        pr[br].append(("box", px, ys + 0.13, 1.15, 0.1, 0.02, 0.3))
        for z in (1.08, 1.22):
            pr[btn].append(("cyl", (px, ys + 0.14, z), (px, ys + 0.15, z), 0.018, 12))
    nm_ = _niche_mats(); np_ = {m: [] for m in nm_.values()}
    _plant_niche(np_, nm_, 1, lo[0] + 0.02, 1, 4.0); _plant_niche(np_, nm_, 1, hi[0] - 0.02, -1, 4.0)
    _emit_mesh("H5LiftPortals", pr); _emit_mesh("H5ElevPlantNiches", np_)
    stats["h5_lifts"] = 4


def _corr2(stats):
    """Corridor: cut-pile runner (small mauve/taupe pattern) + 20 cm cream marble border, central coffer with cove (edge tubes gone), a downlight per door, 3D plant niches between doors."""
    lo, hi = _room(CORR)
    if lo is None:
        return
    for nm in ("H5CorrCove", "H5CorrBorder", "H5CorrNicheS", "H5CorrNicheN"):
        o = bpy.data.objects.get(nm)
        if o is not None:
            bpy.data.objects.remove(o, do_unlink=True)
    m = bpy.data.materials.get("ir_h5_runner2")
    if m is None:                                     # tight repeating diamond-medallion corridor carpet, 45 cm repeat, 3 muted warm tones (orchestrator: the noise runner read as purple blots)
        m = _flat("ir_h5_runner2", (0.42, 0.3, 0.26), 0.95); nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
        tc = N.new("ShaderNodeTexCoord"); geo_ = N.new("ShaderNodeNewGeometry"); mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (1 / 0.45, 1 / 0.45, 1.0); L.new(geo_.outputs["Position"], mp.inputs["Vector"])      # world position: the floor's object space was not metric (r8 test: the pattern averaged to one flat colour)
        fr = N.new("ShaderNodeVectorMath"); fr.operation = "FRACTION"; L.new(mp.outputs["Vector"], fr.inputs[0])
        sb_ = N.new("ShaderNodeVectorMath"); sb_.operation = "SUBTRACT"; sb_.inputs[1].default_value = (0.5, 0.5, 0.0); L.new(fr.outputs[0], sb_.inputs[0])
        ab = N.new("ShaderNodeVectorMath"); ab.operation = "ABSOLUTE"; L.new(sb_.outputs[0], ab.inputs[0])
        se = N.new("ShaderNodeSeparateXYZ"); L.new(ab.outputs[0], se.inputs[0])
        d = N.new("ShaderNodeMath"); d.operation = "ADD"; L.new(se.outputs[0], d.inputs[0]); L.new(se.outputs[1], d.inputs[1])
        cr = N.new("ShaderNodeValToRGB"); cr.color_ramp.interpolation = "CONSTANT"; L.new(d.outputs[0], cr.inputs["Fac"])
        el = cr.color_ramp.elements; el[0].position = 0.0; el[0].color = (0.62, 0.52, 0.38, 1); el[1].position = 0.1; el[1].color = (0.4, 0.29, 0.25, 1)
        for pos, col in ((0.27, (0.55, 0.38, 0.3, 1)), (0.32, (0.4, 0.29, 0.25, 1)), (0.47, (0.62, 0.52, 0.38, 1)), (0.5, (0.4, 0.29, 0.25, 1))):
            e_ = el.new(pos); e_.color = col
        pile = N.new("ShaderNodeTexNoise"); pile.inputs["Scale"].default_value = 400.0; bu = N.new("ShaderNodeBump"); bu.inputs["Strength"].default_value = 0.25; bu.inputs["Distance"].default_value = 0.002
        m2 = N.new("ShaderNodeMix"); m2.data_type = "RGBA"; m2.blend_type = "MULTIPLY"; m2.inputs["Factor"].default_value = 0.12; L.new(cr.outputs["Color"], m2.inputs["A"]); L.new(pile.outputs["Color"], m2.inputs["B"])
        L.new(m2.outputs["Result"], b.inputs["Base Color"])
        L.new(tc.outputs["Object"], pile.inputs["Vector"]); L.new(pile.outputs["Fac"], bu.inputs["Height"]); L.new(bu.outputs["Normal"], b.inputs["Normal"])
    _set_floor(CORR, m)
    fl = _fl(); mar = _veined("ir_h5_marble_strip", (0.88, 0.84, 0.76), (0.7, 0.64, 0.58), 0.6, 0.001, 0.08)
    cream = _flat("ir_h5_ceil", (0.9, 0.88, 0.84), 0.6); cove = _emit("ir_h5_cove", (1.0, 0.78, 0.5), 3.0); disc = _emit("ir_h5_dl", (1.0, 0.86, 0.66), 12.0)
    x0, x1 = lo[0] + 0.1, hi[0] - 0.1; W = hi[1] - lo[1]
    pr = {m_: [] for m_ in (mar, cream, cove, disc)}
    pr[mar] += [("box", (x0 + x1) / 2, lo[1] + 0.05 + 0.1, 0.136, x1 - x0, 0.2, 0.012), ("box", (x0 + x1) / 2, hi[1] - 0.05 - 0.1, 0.136, x1 - x0, 0.2, 0.012)]
    sb = 0.55; zb = ZC - 0.22
    for yc in (lo[1] + sb / 2, hi[1] - sb / 2):
        pr[cream].append(("box", (x0 + x1) / 2, yc, zb + 0.11, x1 - x0, sb, 0.22))
    for yc in (lo[1] + sb + 0.015, hi[1] - sb - 0.015):
        pr[cove].append(("box", (x0 + x1) / 2, yc, zb + 0.04, x1 - x0, 0.03, 0.02))
    nm_ = _niche_mats(); np_ = {m_: [] for m_ in nm_.values()}; nd = 0
    for line, side, yd in ((lo[1] + 0.05, 1, lo[1] + sb / 2), (hi[1] - 0.05, -1, hi[1] - sb / 2)):
        gaps = _door_gaps(0, line, x0, x1)
        for a, b_ in gaps:
            u = (a + b_) / 2
            pr[disc].append(("cyl", (u, yd, zb - 0.004), (u, yd, zb + 0.001), 0.045, 16)); nd += 1
            ld = _light(f"ir_h5_cdl_{side}_{nd}", "SPOT", (u, yd, zb - 0.01), 300, (1.0, 0.8, 0.55)); ld.data.spot_size = math.radians(60)
        for i, (a, b_) in enumerate(_segments(x0, x1, gaps, 1.4)):
            if i % 2 == 0:
                _plant_niche(np_, nm_, 0, line + side * 0.04, side, (a + b_) / 2)
    _emit_mesh("H5CorrCoffer", pr); _emit_mesh("H5CorrPlantNiches", np_)
    for o in [o for o in bpy.data.objects if o.type == "LIGHT" and o.name.startswith("ir_h5_corr_")]:
        o.data.energy *= 0.5
    stats["h5_corr2"] = {"downlights": nd}


def _ensuite_full(stats):
    """The en-suite partitions go to the ceiling, get a 10 cm dark-oak skirting both sides and an oak-cased door opening."""
    oak = _wood("ir_h5_oak", (0.62, 0.45, 0.28)); sk = _flat("ir_h5_skirt", (0.25, 0.18, 0.12), 0.5); n = 0
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("H5Ensuite(")]:
        me = o.data
        for v in me.vertices:
            if v.co.z > 2.0:
                v.co.z = ZC - 0.005
        b0, b1 = _bb(o); prims = []
        for p in me.polygons:
            pass
        # skirting + casing along each wall piece (one box per loose part)
        import bmesh
        bm = bmesh.new(); bm.from_mesh(me); bm.verts.ensure_lookup_table()
        seen = set(); parts = []
        for v in bm.verts:
            if v.index in seen:
                continue
            stack = [v]; isl = []
            while stack:
                q = stack.pop()
                if q.index in seen:
                    continue
                seen.add(q.index); isl.append(q.co.copy())
                stack += [e.other_vert(q) for e in q.link_edges]
            parts.append(isl)
        bm.free()
        for isl in parts:
            xs = [c.x for c in isl]; ys = [c.y for c in isl]; ax0, ax1, ay0, ay1 = min(xs), max(xs), min(ys), max(ys)
            if ax1 - ax0 > ay1 - ay0:
                prims += [("box", (ax0 + ax1) / 2, ay0 - 0.01, 0.18, ax1 - ax0, 0.02, 0.1), ("box", (ax0 + ax1) / 2, ay1 + 0.01, 0.18, ax1 - ax0, 0.02, 0.1)]
                cas = [(ax0, (ay0 + ay1) / 2), (ax1, (ay0 + ay1) / 2)]; along_x = True
            else:
                prims += [("box", ax0 - 0.01, (ay0 + ay1) / 2, 0.18, 0.02, ay1 - ay0, 0.1), ("box", ax1 + 0.01, (ay0 + ay1) / 2, 0.18, 0.02, ay1 - ay0, 0.1)]
                cas = [((ax0 + ax1) / 2, ay0), ((ax0 + ax1) / 2, ay1)]; along_x = False
            for cx_, cy_ in cas:                                  # 7 cm oak casing on each wall end (the door jambs where an end faces the gap)
                prims.append(("box", cx_, cy_, 1.15, 0.07 if along_x else 0.12, 0.12 if along_x else 0.07, 2.1))
        o.data.update()
        if prims:
            _fl().mesh_object(f"H5EnsuiteTrim({o.name[10:-1]})", [(sk, [p for p in prims if p[6] == 0.1]), (oak, [p for p in prims if p[6] != 0.1])], bevel=False); n += 1
    stats["h5_ensuite_full"] = n



def _guests(stats):
    """User 10-25: guest rooms differ a little -- per room id (deterministic) one of three states, real assets only:
    fresh (nothing personal), checked-in (suitcase on a rack or the floor, shoes by the bed, laptop on the desk, phone + water bottle on a nightstand, shirt over the chair),
    lived-in (blanket thrown on the bed foot, towel on the duvet, book + mug on a nightstand, room-service tray with plate + cup on the desk, trousers over the armchair);
    bedside lamps on / off per room."""
    out = {"fresh": 0, "checked_in": 0, "lived_in": 0}
    for f in sorted([o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("bedroom_0/") and o.name.endswith(".floor")], key=lambda o: o.name):
        rn = f.name[:-6]; lo, hi = _fbox(f); k = int(rn.split("/")[1]); rg = random.Random(1000 + k); fz = lo[2]
        state = ("fresh", "checked_in", "lived_in")[(k * 7 + 1) % 3]; out[state] += 1
        if k % 2:                                                  # lamps off in every other room
            for s_ in (-1, 1):
                ld = bpy.data.objects.get(f"ir_h5_lamp_{rn}_{s_}")
                if ld is not None:
                    ld.data.energy = 0.0
        if state == "fresh":
            continue
        beds = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("SoftBedFactory", "H5SpareBed")) and _in_room(o, lo, hi)]
        if not beds:
            continue
        cx, cy, h, L, W, zt = _bed_frame(beds[0]); zt = max(zt, 0.45)
        def pt(a, b):
            return cx + h[0] * a - h[1] * b, cy + h[1] * a + h[0] * b
        yfoot = math.atan2(-h[1], -h[0])
        stands = [o for o in bpy.data.objects if o.name.startswith("Real_nightstand") and _in_room(o, lo, hi)]
        desks = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("AboDeskFactory", "DeskFactory", "H2Desk")) and _in_room(o, lo, hi)]
        chairs = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("AboCafechairFactory", "AboChairFactory", "OfficeChairFactory", "AccentArmchairFactory", "AboArmchairFactory")) and _in_room(o, lo, hi)]
        st = stands[rg.randrange(len(stands))] if stands else None
        def on_top(o):
            b0, b1 = _bb(o); return (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2, b1[2]
        if state == "checked_in":
            sx, sy = pt(-L / 2 - 0.55, W / 2 + 0.2)
            if lo[0] + 0.4 < sx < hi[0] - 0.4 and lo[1] + 0.4 < sy < hi[1] - 0.4:
                rk = ra.abo("luggagerack", 1, sx, sy, fz, yfoot, fit=(0.7, 0.5, 0.55)) if rg.random() < 0.5 else None
                ra.abo("suitcase", k, sx, sy, ra.top(rk) if rk is not None else fz, yfoot + rg.uniform(-0.3, 0.3), fit=(0.75, 0.5, 0.35))
            for j in range(2):
                ra.abo("shoes", k * 3 + j, *pt(-0.2 - j * 0.25, -(W / 2 + 0.35)), fz, yfoot + rg.uniform(-0.4, 0.4), fit=(0.3, 0.15, 0.15))
            if st is not None:
                x_, y_, z_ = on_top(st)
                ra.abo("phone", k, x_ - 0.08, y_, z_, rg.uniform(0, 6.28), fit=(0.17, 0.09, 0.02)); ra.lib("BottleFactory", k, x_ + 0.1, y_ + 0.05, z_, 0.0, 1.0)
            if desks:
                x_, y_, z_ = on_top(desks[0]); ra.abo("laptop", k, x_, y_, z_, rg.uniform(-0.5, 0.5), fit=(0.36, 0.27, 0.3))
            if chairs:
                x_, y_, z_ = on_top(chairs[0]); ra.inf("inf:ShirtFactory", k, x_, y_, z_ - 0.05, rg.uniform(0, 6.28), fit=(0.6, 0.6, 0.2))
        else:
            ra.inf("inf:BlanketFactory", k, *pt(-L / 2 + 0.35, rg.uniform(-0.2, 0.2)), zt + 0.12, yfoot + rg.uniform(-0.4, 0.4), fit=(1.1, 0.6, 0.1))
            ra.abo("towel", k, *pt(-L / 2 + 0.2, rg.uniform(-0.3, 0.3)), zt + 0.14, rg.uniform(0, 6.28), fit=(0.4, 0.4, 0.08))
            if st is not None:
                x_, y_, z_ = on_top(st)
                ra.abo("book", k, x_ - 0.06, y_, z_, rg.uniform(0, 6.28), fit=(0.25, 0.18, 0.05)); ra.abo("mug", k, x_ + 0.1, y_ + 0.04, z_, rg.uniform(0, 6.28), fit=(0.12, 0.12, 0.11))
            if desks:
                x_, y_, z_ = on_top(desks[0]); tr = ra.abo("tray", k, x_, y_, z_, rg.uniform(-0.3, 0.3), fit=(0.5, 0.36, 0.06))
                zt_ = ra.top(tr) - 0.04 if tr is not None else z_
                ra.lib("PlateFactory", 500 + k, x_ - 0.06, y_, zt_, 0.0, 0.8); ra.lib("CupFactory", 500 + k, x_ + 0.14, y_ + 0.06, zt_, rg.uniform(0, 6.28), 1.0)
            if chairs:
                x_, y_, z_ = on_top(chairs[-1]); ra.inf("inf:PantsFactory", k, x_, y_, z_ - 0.05, rg.uniform(0, 6.28), fit=(0.6, 0.5, 0.15))
    stats["h5_guests"] = out


# ---- r9 batch (SUB2 floorH5_hotel_r9.md): stalls2, banq2, lobby2, finish, windows, vary -------------------------------------------------

def _panel_mesh(name, mat, verts_fn, nu, nv):
    """A grid mesh from verts_fn(i, j) -> (x, y, z), nu x nv vertices, smooth shaded."""
    import bmesh
    bm = bmesh.new(); vs = [[bm.verts.new(verts_fn(i, j)) for j in range(nv)] for i in range(nu)]
    for i in range(nu - 1):
        for j in range(nv - 1):
            bm.faces.new((vs[i][j], vs[i + 1][j], vs[i + 1][j + 1], vs[i][j + 1]))
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free(); me.materials.append(mat)
    for p in me.polygons:
        p.use_smooth = True
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    sol = o.modifiers.new("t", "SOLIDIFY"); sol.thickness = 0.004
    return o


def _bed_walls(stats):
    """r14 #3: bare bedroom walls. On every free stretch of the side / window walls (clear of doors, windows, wardrobes, slats, furniture touching the wall at 0.9-2.1 m): one large ABO framed print, a mirror (round brass-framed or tall rectangular, by room id), and a pair of brass wall sconces with pleated emissive shades + a warm light; counts and picks vary by room id."""
    import wall_face
    n = 0; sc = 0; mir = 0; art = 0
    brass = _flat("ir_h5_brass_w", (0.74, 0.55, 0.24), 0.3, 1.0); glass = _flat("ir_h5_mirror_w", (0.85, 0.87, 0.9), 0.04, 1.0); shade = _emit("ir_h5_shade", (1.0, 0.86, 0.66), 3.0)
    for f in sorted([o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("bedroom_0/") and o.name.endswith(".floor")], key=lambda o: o.name):
        rn = f.name[:-6]; k = int(rn.split("/")[1]); rg = random.Random(900 + k); lo, hi = _fbox(f)
        if lo is None:
            continue
        obs = [_bb(o) for o in bpy.data.objects if o.type == "MESH" and o is not f and not o.name.endswith((".floor", ".ceiling", ".wall", ".exterior", ".meshed")) and not o.name.startswith(("Baseboard", "H5Ceil", "H5Floor", "H5Room")) and o.name != rn
               and _bb(o)[1][2] > 0.9 and _bb(o)[0][2] < 2.1 and _bb(o)[1][0] > lo[0] - 0.05 and _bb(o)[0][0] < hi[0] + 0.05 and _bb(o)[1][1] > lo[1] - 0.05 and _bb(o)[0][1] < hi[1] + 0.05]
        free = []
        for side in "WESN":
            ax = side in "WE"; so = 1 if side in "WS" else -1; line = {"W": lo[0], "E": hi[0], "S": lo[1], "N": hi[1]}[side]
            a0, a1 = (lo[1], hi[1]) if ax else (lo[0], hi[0])
            iv = []
            for b0, b1 in obs:
                near = (b0[0] < line + 0.35 and b1[0] > line - 0.35) if ax else (b0[1] < line + 0.35 and b1[1] > line - 0.35)
                if near:
                    iv.append(((b0[1] - 0.2, b1[1] + 0.2) if ax else (b0[0] - 0.2, b1[0] + 0.2)))
            cur = a0 + 0.3
            for q0, q1 in sorted(iv):
                if q0 - cur >= 1.0:
                    free.append((q0 - cur, side, cur, q0))
                cur = max(cur, q1)
            if a1 - 0.3 - cur >= 1.0:
                free.append((a1 - 0.3 - cur, side, cur, a1 - 0.3))
        free.sort(reverse=True)
        used = []
        for L_, side, c0, c1 in free[:4]:
            ax = side in "WE"; so = 1 if side in "WS" else -1; line = {"W": lo[0], "E": hi[0], "S": lo[1], "N": hi[1]}[side]; u = (c0 + c1) / 2
            yaw = math.atan2(0, so) if ax else math.atan2(so, 0)
            P = lambda dd, uu=u: ((line + so * dd, uu) if ax else (uu, line + so * dd))
            kind = (0, 1, 0, 2)[len(used) % 4]                                             # r15: art first, then mirror, art, sconces (was a rotating mix that could skip the art)
            if kind == 0:                                                                  # large print
                x_, y_ = P(0.03)
                if ra.abo("wallart", 500 + k * 7 + len(used), x_, y_, 1.2, yaw, fit=(min(1.4, L_ - 0.3), 0.06, 1.0)) is not None:
                    art += 1
            elif kind == 1:                                                                # mirror
                pr = {brass: [], glass: []}
                if k % 2 == 0:
                    for r_, mt, d0, d1 in ((0.46, brass, 0.0, 0.03), (0.41, glass, 0.03, 0.045)):
                        a_, b_ = P(d0), P(d1); pr[mt].append(("cyl", (a_[0], a_[1], 1.5), (b_[0], b_[1], 1.5), r_, 32))
                    if ax:
                        pass
                else:
                    w_ = min(0.7, L_ - 0.3); x_, y_ = P(0.02); x2, y2 = P(0.04)
                    pr[brass].append(("box", x_, y_, 1.4, 0.03, w_ + 0.06, 1.46) if ax else ("box", x_, y_, 1.4, w_ + 0.06, 0.03, 1.46))
                    pr[glass].append(("box", x2, y2, 1.4, 0.012, w_, 1.4) if ax else ("box", x2, y2, 1.4, w_, 0.012, 1.4))
                _emit_mesh(f"H5BedMirror({rn}|{len(used)})", pr); mir += 1
            else:                                                                          # a pair of sconces
                pr = {brass: [], shade: []}
                for du in (-0.55, 0.55):
                    a_, b_, c_ = P(0.012, u + du), P(0.1, u + du), P(0.16, u + du)
                    pr[brass].append(("cyl", (a_[0], a_[1], 1.6), (a_[0] + (so * 0.014 if ax else 0), a_[1] + (0 if ax else so * 0.014), 1.6), 0.05, 20))
                    pr[brass].append(("cyl", (a_[0], a_[1], 1.6), (b_[0], b_[1], 1.6), 0.01, 8))
                    pr[shade].append(("cyl", (c_[0], c_[1], 1.5), (c_[0], c_[1], 1.7), 0.065, 20))
                    _light(f"ir_h5_sconce_{rn}_{len(used)}_{du}", "POINT", (c_[0], c_[1], 1.6), 12, (1.0, 0.8, 0.55), r=0.05)
                _emit_mesh(f"H5BedSconce({rn}|{len(used)})", pr); sc += 2
            used.append(side); n += 1
    stats["h5_bed_walls"] = {"pieces": n, "art": art, "mirrors": mir, "sconces": sc}


def _stalls2(stats):
    """r9 #3: HPL toilet cubicles: 25 mm panels raised 150 mm on stainless feet, full-height pilasters, an aluminium headrail, a door leaf with a 10 mm gap, 3 hinges, an indicator lock + pull."""
    for o in [o for o in bpy.data.objects if o.name.startswith("H5Stall(")]:
        bpy.data.objects.remove(o, do_unlink=True)
    hpl = _wood("ir_h5_hpl_walnut", (0.3, 0.19, 0.11)); ss = _flat("ir_h5_stainless", (0.75, 0.75, 0.76), 0.25, 1.0); red = _emit("ir_h5_lockred", (0.9, 0.12, 0.08), 1.5); dkk = _flat("ir_h5_stall_black", (0.02, 0.02, 0.02), 0.5); n = 0      # r14: dark walnut laminate: the beige slabs vanished into the beige walls at 512 px
    for f in list(bpy.data.objects):
        if not (f.type == "MESH" and f.name.startswith("restroom_0/") and f.name.endswith(".floor")):
            continue
        lo, hi = _fbox(f); fz = hi[2]
        for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("ToiletFactory", "ToiletStallFactory")) and _in_room(o, lo, hi)]:
            b0, b1 = _bb(o); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
            d = {"W": cx - lo[0], "E": hi[0] - cx, "S": cy - lo[1], "N": hi[1] - cy}; w = min(d, key=d.get)
            depth, half, t = 1.5, 0.46, 0.025; z0, z1 = fz + 0.15, fz + 1.95
            if w in ("W", "E"):
                sg = 1 if w == "W" else -1; base = (lo[0] if w == "W" else hi[0]); along = (0, 1)
                at = lambda a, dd, z, sa, sd, sz: ("box", base + sg * dd, cy + a, z, sd, sa, sz)
                atc = lambda a, dd, z0_, z1_, r: ("cyl", (base + sg * dd, cy + a, z0_), (base + sg * dd, cy + a, z1_), r, 12)
            else:
                sg = 1 if w == "S" else -1; base = (lo[1] if w == "S" else hi[1])
                at = lambda a, dd, z, sa, sd, sz: ("box", cx + a, base + sg * dd, z, sa, sd, sz)
                atc = lambda a, dd, z0_, z1_, r: ("cyl", (cx + a, base + sg * dd, z0_), (cx + a, base + sg * dd, z1_), r, 12)
            P = {hpl: [], ss: [], red: [], dkk: []}
            for a in (-half, half):                                # side panels, raised, with two stainless feet each
                P[hpl].append(at(a, depth / 2, (z0 + z1) / 2, t, depth - 0.12, z1 - z0))
                for dd in (0.25, depth - 0.25):
                    P[ss].append(atc(a, dd, fz, z0 + 0.02, 0.018))
            for a in (-half, half):                                # pilasters floor-to-headrail at the front
                P[hpl].append(at(a, depth, (fz + 0.1 + z1 + 0.05) / 2, 0.1, t, z1 + 0.05 - fz - 0.1))
                P[ss].append(at(a, depth, fz + 0.05, 0.12, 0.04, 0.1))  # pilaster shoe
            P[ss].append(at(0.0, depth + 0.025, z1 + 0.06, 2 * half + 0.12, 0.06, 0.08))      # headrail (r14: bigger so it reads)
            P[ss].append(at(0.0, depth + 0.012, z0 + 0.09, 2 * half - 0.12, 0.012, 0.16))     # r14: stainless kick plate on the door
            for a in (-half + 0.06, half - 0.06):                                           # r14: dark reveal strips along the door edges (20 mm gaps)
                P[dkk].append(at(a, depth + 0.002, (z0 + z1) / 2, 0.02, 0.012, z1 - z0))
            dw = 2 * half - 0.1 - 0.04                                                      # door leaf, 10 mm gaps, a hair inside the front line
            P[hpl].append(at(0.0, depth - 0.01, (z0 + z1) / 2, dw, t, z1 - z0))
            for z in (z0 + 0.15, (z0 + z1) / 2, z1 - 0.15):                                # hinges on the left pilaster
                P[ss].append(atc(-half + 0.06, depth + 0.012, z - 0.06, z + 0.06, 0.022)); P[ss].append(at(-half + 0.06, depth + 0.006, z, 0.05, 0.01, 0.16))
            P[ss].append(at(half - 0.12, depth + 0.016, fz + 1.0, 0.12, 0.02, 0.08))       # indicator lock body (r14: bigger)
            P[red].append(at(half - 0.12, depth + 0.028, fz + 1.0, 0.05, 0.004, 0.035))      # red 'occupied' window
            P[ss].append(at(half - 0.24, depth + 0.03, fz + 1.0, 0.03, 0.04, 0.2))          # pull handle (r14: bigger)
            P[ss].append(at(-half + 0.03, depth - 0.45, fz + 0.75, 0.03, 0.16, 0.14)); P[dkk].append(at(-half + 0.047, depth - 0.45, fz + 0.75, 0.006, 0.1, 0.1))      # r14: toilet-paper holder on the side panel
            _emit_mesh(f"H5Stall2({f.name[:-6]}|{n})", P); n += 1
    stats["h5_stalls2"] = n


def _carpet_banquet():
    """Banquet swirl / medallion carpet: world-space distorted rings in 3 warm tones + a 2.4 m medallion lattice, cut-pile bump."""
    m = bpy.data.materials.get("ir_h5_banq_carpet")
    if m is not None:
        return m
    m = _flat("ir_h5_banq_carpet", (0.6, 0.48, 0.36), 0.95); nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    geo = N.new("ShaderNodeNewGeometry"); wv = N.new("ShaderNodeTexWave"); wv.wave_type = "RINGS"; wv.inputs["Scale"].default_value = 0.55; wv.inputs["Distortion"].default_value = 9.0
    wv.inputs["Detail"].default_value = 2.0; wv.inputs["Detail Scale"].default_value = 1.5; L.new(geo.outputs["Position"], wv.inputs["Vector"])
    cr = N.new("ShaderNodeValToRGB"); el = cr.color_ramp.elements; L.new(wv.outputs["Fac"], cr.inputs["Fac"])
    el[0].position = 0.0; el[0].color = (0.72, 0.6, 0.44, 1); el[1].position = 1.0; el[1].color = (0.72, 0.6, 0.44, 1)
    for pos, col in ((0.35, (0.72, 0.6, 0.44, 1)), (0.42, (0.42, 0.3, 0.22, 1)), (0.55, (0.42, 0.3, 0.22, 1)), (0.62, (0.82, 0.74, 0.6, 1)), (0.8, (0.82, 0.74, 0.6, 1)), (0.86, (0.3, 0.33, 0.45, 1)), (0.9, (0.72, 0.6, 0.44, 1))):
        e_ = el.new(pos); e_.color = col
    pile = N.new("ShaderNodeTexNoise"); pile.inputs["Scale"].default_value = 500.0; bu = N.new("ShaderNodeBump"); bu.inputs["Strength"].default_value = 0.2; bu.inputs["Distance"].default_value = 0.002
    L.new(geo.outputs["Position"], pile.inputs["Vector"]); L.new(pile.outputs["Fac"], bu.inputs["Height"]); L.new(bu.outputs["Normal"], b.inputs["Normal"])
    mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.blend_type = "MULTIPLY"; mx.inputs["Factor"].default_value = 0.1
    L.new(cr.outputs["Color"], mx.inputs["A"]); L.new(pile.outputs["Color"], mx.inputs["B"]); L.new(mx.outputs["Result"], b.inputs["Base Color"])
    return m


def _dress_chair(ch, satin, wood):
    """r13: the HSSD chair had EVERY slot swapped to satin, so white legs + white seat read as a cube from the cameras. Faces below ~42 % of the chair's height get dark walnut (legs, lower rails), the rest satin."""
    me = ch.data = ch.data.copy(); zs = [v.co.z for v in me.vertices]
    if not zs:
        return
    z0, z1 = min(zs), max(zs); cut = z0 + 0.42 * (z1 - z0)
    me.materials.clear(); me.materials.append(satin); me.materials.append(wood)
    for p_ in me.polygons:
        p_.material_index = 1 if p_.center.z < cut else 0


def _crystal_spray(name, cx, cy, zc, mats):
    """r13: a sunburst crystal chandelier: brass canopy + stem, a brass hub, 60 radial strands, each a thin brass wire strung with faceted crystal beads and a teardrop at the tip (REF: crystal sprays with bead strings)."""
    import bmesh
    brass, crys = mats; bm = bmesh.new(); rg = random.Random(int(cx * 10 + cy))
    def cyl(p0, p1, r, seg=6, mi=0):
        d = Vector(p1) - Vector(p0); L = d.length
        if L < 1e-5:
            return
        res = bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r, radius2=r, depth=L)
        rot = d.to_track_quat("Z", "Y").to_matrix().to_4x4(); bmesh.ops.transform(bm, matrix=rot, verts=res["verts"]); bmesh.ops.translate(bm, vec=(Vector(p0) + Vector(p1)) / 2, verts=res["verts"])
        for f in {f for v in res["verts"] for f in v.link_faces}:
            f.material_index = mi
    def bead(c, r, sz=1.0, mi=1):
        res = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=r)
        bmesh.ops.scale(bm, vec=(1, 1, sz), verts=res["verts"]); bmesh.ops.translate(bm, vec=c, verts=res["verts"])
        for f in {f for v in res["verts"] for f in v.link_faces}:
            f.material_index = mi
    top = Vector((cx, cy, 3.62)); hub = Vector((cx, cy, zc))
    cyl(top, hub, 0.012, 8, 0); bead(hub, 0.11, 1.0, 0); cyl((cx, cy, 3.62), (cx, cy, 3.5), 0.1, 16, 0)
    for k in range(60):
        az = 2 * math.pi * k / 60 + rg.uniform(-0.04, 0.04); el = math.radians(rg.choice((-55, -35, -15, 5, 25, 45, 60)) + rg.uniform(-6, 6))
        d = Vector((math.cos(az) * math.cos(el), math.sin(az) * math.cos(el), math.sin(el))); L = rg.uniform(0.5, 0.85)
        tip = hub + d * L; cyl(hub + d * 0.1, tip, 0.0035, 5, 0)
        for t in range(1, 9):
            bead(hub + d * (0.1 + (L - 0.1) * t / 9.0), 0.012 + 0.004 * (t % 2), 1.0, 1)
        bead(tip, 0.028, 1.9, 1)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free(); me.materials.append(brass); me.materials.append(crys)
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    return o


def _banq2(stats):
    """r9 #4: crystal chandeliers (HSSD Leyland tiered / Karrington / 12-light, the 2972-poly halogen drum excluded), swirl banquet carpet, real fabric slip covers on every chair."""
    lo, hi = _room(HALL)
    if lo is None:
        return
    _set_floor(HALL, _carpet_banquet())
    k = 0
    for o in [o for o in bpy.data.objects if o.name.startswith("Real_chandelier") and _in_room(o, lo, hi)]:
        b0, b1 = _bb(o); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
        bpy.data.objects.remove(o, do_unlink=True)
        crys0 = bpy.data.materials.get("ir_h5_crystal_glass"); brass0 = _flat("ir_h5_chand_brass", (0.75, 0.58, 0.28), 0.25, 1.0)
        if crys0 is None:
            crys0 = _flat("ir_h5_crystal_glass", (0.97, 0.97, 1.0), 0.02); b0_ = crys0.node_tree.nodes["Principled BSDF"]
            b0_.inputs["Transmission Weight"].default_value = 1.0; b0_.inputs["IOR"].default_value = 1.55
            b0_.inputs["Emission Color"].default_value = (1.0, 0.85, 0.6, 1); b0_.inputs["Emission Strength"].default_value = 0.6
        _crystal_spray(f"H5CrystalChandelier{k}", cx, cy, ZC - 1.3, (brass0, crys0)); k += 1
    crys = bpy.data.materials.get("ir_h5_crystal_glass")
    if crys is None:                                                  # r11 #3: the HSSD fixtures' drops rendered as opaque white rods: clear faceted crystal with a faint warm glow
        crys = _flat("ir_h5_crystal_glass", (0.97, 0.97, 1.0), 0.02); b_ = crys.node_tree.nodes["Principled BSDF"]
        b_.inputs["Transmission Weight"].default_value = 1.0; b_.inputs["IOR"].default_value = 1.55
        b_.inputs["Emission Color"].default_value = (1.0, 0.85, 0.6, 1); b_.inputs["Emission Strength"].default_value = 0.6
    bpy.context.view_layer.update()                                   # the fixtures were just placed: world bounds are stale until an update
    for o in [o for o in bpy.data.objects if o.name.startswith("Real_hssd") and o.type == "MESH" and _in_room(o, lo, hi) and _bb(o)[0][2] > 1.8]:
        o.data = o.data.copy()
        for i, m_ in enumerate(o.data.materials):
            pb = m_.node_tree.nodes.get("Principled BSDF") if m_ and m_.node_tree else None
            if pb is None or pb.inputs["Metallic"].default_value < 0.5:
                o.data.materials[i] = crys
    stats["h5_banq_chandeliers"] = k
    for o in [o for o in bpy.data.objects if o.name.startswith(("H5ChairCovers", "H5ChairBows", "H5ChairCover"))]:
        bpy.data.objects.remove(o, do_unlink=True)                    # r11 #1: the box slip covers + bows read as white cubes
    satin = bpy.data.materials.get("ir_h5_cover_satin")
    if satin is None:
        satin = _flat("ir_h5_cover_satin", (0.92, 0.91, 0.88), 0.75); b_ = satin.node_tree.nodes["Principled BSDF"]
        b_.inputs["Sheen Weight"].default_value = 0.8; b_.inputs["Sheen Roughness"].default_value = 0.35
    tables = []
    for o in bpy.data.objects:
        if o.name.startswith(("H5Tablecloth", "TableDiningFactory")) and o.type == "MESH" and _in_room(o, lo, hi):
            b0, b1 = _bb(o); tables.append(((b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2))
    nc = 0
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("ChairFactory", "CafeChairFactory", "DiningChairFactory")) and _in_room(o, lo, hi)]:
        b0, b1 = _bb(o); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
        if not tables or b1[2] > 1.3:
            continue
        tx, ty = min(tables, key=lambda t_: (t_[0] - cx) ** 2 + (t_[1] - cy) ** 2)
        yaw = math.atan2(ty - cy, tx - cx)                              # faces its table
        ch = ra.hssd(r"Upholstered Dining Chair|Parsons|Dining Chair", 300, cx, cy, b0[2], yaw, fit=(0.5, 0.5, 0.95), size=(0.75, 1.1))
        if ch is None:
            continue
        _dress_chair(ch, satin, _wood("ir_h5_wood_dark", (0.2, 0.11, 0.06)))
        bpy.data.objects.remove(o, do_unlink=True); nc += 1
    stats["h5_banq_covers"] = nc


def _travertine():
    m = bpy.data.materials.get("ir_h5_travertine")
    if m is not None:
        return m
    m = _flat("ir_h5_travertine", (0.82, 0.74, 0.62), 0.45); nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    geo = N.new("ShaderNodeNewGeometry"); mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (1.0, 1.0, 14.0); L.new(geo.outputs["Position"], mp.inputs["Vector"])   # horizontal bedding streaks
    no = N.new("ShaderNodeTexNoise"); no.inputs["Scale"].default_value = 3.0; no.inputs["Detail"].default_value = 8.0; L.new(mp.outputs["Vector"], no.inputs["Vector"])
    mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.inputs["A"].default_value = (0.86, 0.78, 0.66, 1); mx.inputs["B"].default_value = (0.7, 0.6, 0.47, 1); L.new(no.outputs["Fac"], mx.inputs["Factor"])
    L.new(mx.outputs["Result"], b.inputs["Base Color"])
    pit = N.new("ShaderNodeTexVoronoi"); pit.inputs["Scale"].default_value = 60.0; bu = N.new("ShaderNodeBump"); bu.inputs["Strength"].default_value = 0.15; bu.inputs["Distance"].default_value = 0.001
    L.new(geo.outputs["Position"], pit.inputs["Vector"]); L.new(pit.outputs["Distance"], bu.inputs["Height"]); L.new(bu.outputs["Normal"], b.inputs["Normal"])
    return m


def _ring_pendant(name, cx, cy, zc, mat_b, mat_led):
    """Two stacked brass rings (0.9 / 0.65 m) with an LED band on the inner face, hung on thin cables."""
    import bmesh
    bm = bmesh.new(); mats = []
    for r, z in ((0.45, zc), (0.33, zc - 0.32)):
        for slot, (rr, h, off) in enumerate(((r, 0.05, 0.0), (r - 0.012, 0.03, -0.004))):
            n = 64; ring_o = [bm.verts.new((cx + (rr + 0.015) * math.cos(2 * math.pi * i / n), cy + (rr + 0.015) * math.sin(2 * math.pi * i / n), z + off)) for i in range(n)]
            ring_i = [bm.verts.new((cx + (rr - 0.015) * math.cos(2 * math.pi * i / n), cy + (rr - 0.015) * math.sin(2 * math.pi * i / n), z + off)) for i in range(n)]
            top_o = [bm.verts.new((v.co.x, v.co.y, v.co.z + h)) for v in ring_o]; top_i = [bm.verts.new((v.co.x, v.co.y, v.co.z + h)) for v in ring_i]
            for i in range(n):
                j = (i + 1) % n
                for a_, b_, c_, d_ in ((ring_o[i], ring_o[j], top_o[j], top_o[i]), (ring_i[j], ring_i[i], top_i[i], top_i[j]), (top_o[i], top_o[j], top_i[j], top_i[i]), (ring_i[i], ring_i[j], ring_o[j], ring_o[i])):
                    f = bm.faces.new((a_, b_, c_, d_)); f.material_index = slot; f.smooth = True
        for a in (0.0, 2.1, 4.2):
            pass
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free(); me.materials.append(mat_b); me.materials.append(mat_led)
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    cab = [("cyl", (cx + 0.45 * math.cos(a), cy + 0.45 * math.sin(a), zc + 0.05), (cx + 0.3 * math.cos(a), cy + 0.3 * math.sin(a), ZC), 0.002, 6) for a in (0.3, 2.4, 4.5)]
    _fl().mesh_object(name + "Cables", [(mat_b, cab)], bevel=False)
    return o


def _lobby2(stats):
    """r9 #5: banquet lobby dressing: travertine panelled walls with reveals, a stone console with lamps + flowers, 2 armchair pairs with side tables, 2 stacked brass ring pendants, floor plants, art."""
    lo, hi = _room(LOBBY)
    if lo is None:
        return
    fl = _fl(); trav = _travertine(); dark = _flat("ir_h5_reveal", (0.18, 0.15, 0.12), 0.6)
    pr = {trav: [], dark: []}; zt = ZC - 0.25
    for line, side in ((lo[1] + 0.003, 1), (hi[1] - 0.003, -1)):
        for a, b_ in _segments(lo[0] + 0.1, hi[0] - 0.3, _door_gaps(0, line, lo[0], hi[0])):
            pr[dark].append(("box", (a + b_) / 2, line + side * 0.004, (0.12 + zt) / 2, b_ - a, 0.008, zt - 0.12))
            nx = max(1, int((b_ - a) / 1.2)); pw = (b_ - a) / nx
            for i in range(nx):
                for zz0, zz1 in ((0.15, 1.3), (1.32, 2.47), (2.49, zt - 0.02)):
                    pr[trav].append(("box", a + (i + 0.5) * pw, line + side * 0.024, (zz0 + zz1) / 2, pw - 0.012, 0.03, zz1 - zz0 - 0.012))
    for line, side in ((lo[0] + 0.003, 1),):
        for a, b_ in _segments(lo[1] + 0.1, hi[1] - 0.1, _door_gaps(1, line, lo[1], hi[1])):
            pr[dark].append(("box", line + side * 0.004, (a + b_) / 2, (0.12 + zt) / 2, 0.008, b_ - a, zt - 0.12))
            ny = max(1, int((b_ - a) / 1.2)); pw = (b_ - a) / ny
            for i in range(ny):
                for zz0, zz1 in ((0.15, 1.3), (1.32, 2.47), (2.49, zt - 0.02)):
                    pr[trav].append(("box", line + side * 0.024, a + (i + 0.5) * pw, (zz0 + zz1) / 2, 0.03, pw - 0.012, zz1 - zz0 - 0.012))
    _emit_mesh("H5LobbyTravertine", pr)
    xc = hi[0] - 0.5; yc = (lo[1] + hi[1]) / 2 - 1.6                     # console in front of the lattice wall (east), south half
    con = ra.abo("console", 41, xc, yc, lo[2], math.pi / 2, fit=(1.9, 0.5, 0.95))
    zc_ = ra.top(con) if con is not None else lo[2] + 0.85
    for dy in (-0.65, 0.65):
        ra.abo("tablelamp", 43 + int(dy > 0), xc, yc + dy, zc_, 0.0, fit=(0.4, 0.4, 0.7))
    ra.abo("bouquet", 47, xc, yc, zc_, 0.0, fit=(0.5, 0.5, 0.6))
    for gi, (gx, gy) in enumerate(((lo[0] + 2.2, lo[1] + 2.3), (lo[0] + 2.2, hi[1] - 2.6))):    # two armchair pairs facing each other across a side table
        for s_ in (-1, 1):
            ra.abo("armchair", 50 + gi * 2 + (s_ > 0), gx + s_ * 0.75, gy, lo[2], (math.pi / 2 if s_ < 0 else -math.pi / 2), fit=(0.9, 0.9, 1.0))
        ra.abo("sidetable", 60 + gi, gx, gy, lo[2], 0.0, fit=(0.55, 0.55, 0.6))
    for i, (px, py) in enumerate(((lo[0] + 0.6, lo[1] + 0.6), (hi[0] - 0.9, hi[1] - 0.7), (lo[0] + 0.6, hi[1] - 0.6))):
        ra.abo("planter", 70 + i, px, py, lo[2], 0.0, fit=(0.8, 0.8, 1.8))
    for i, yy in enumerate((lo[1] + 3.0, hi[1] - 3.4)):
        ra.abo("wallart", 80 + i, lo[0] + 0.07, yy, lo[2] + 1.2, -math.pi / 2, fit=(1.2, 0.08, 1.0))
    brass = _flat("ir_h5_brass_ring", (0.78, 0.6, 0.3), 0.25, 1.0); led = _emit("ir_h5_ring_led", (1.0, 0.85, 0.6), 8.0)
    for i, (gx, gy) in enumerate(((lo[0] + 2.2, lo[1] + 2.3), (lo[0] + 2.2, hi[1] - 2.6))):
        _ring_pendant(f"H5RingPendant{i}", gx, gy, ZC - 0.75, brass, led)
        _light(f"ir_h5_ring_{i}", "POINT", (gx, gy, ZC - 0.95), 260, (1.0, 0.82, 0.58), r=0.3)
    stats["h5_lobby2"] = 1


def _finish(stats):
    """r9 #6/#7: lift hall: dark Emperador-style veined marble floor + the ochre wood wall slab turned to dark veined marble panels with a brass band; corridor walls: walnut veneer with brass inlay strips."""
    lo, hi = _room(ELEV)
    if lo is not None:
        dm = _veined("ir_h5_emperador", (0.3, 0.22, 0.17), (0.78, 0.7, 0.58), 0.9, 0.002, 0.1, vein_scale=2.5)
        _set_floor(ELEV, dm)
        wm = _veined("ir_h5_emperador_wall", (0.24, 0.17, 0.13), (0.86, 0.78, 0.66), 0.6, 0.004, 0.15, vein_scale=3.2)      # r13: finer, darker, higher-contrast veins: the 1.2 m flat tint read as one ochre slab
        o = bpy.data.objects.get("H5ElevWallS")
        if o is not None and o.data.materials:
            o.data = o.data.copy()
            for i in range(len(o.data.materials)):
                o.data.materials[i] = wm
        for line, side in ((lo[0] + 0.003, 1), (hi[0] - 0.003, -1)):       # the side walls (the flat ochre wall paint) get the same dark marble, between the doors / niches
            _clad(f"H5ElevMarble{side}", wm, 1, line, side, lo[1] + 0.3, hi[1] - 0.1, 0.1, ZC - 0.35, sorted(_door_gaps(1, line, lo[1], hi[1]) + [(3.4, 4.6)]))
        for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("CafeCounterFactory", "ReceptionDeskFactory")) and _in_room(o, lo, hi)]:
            b0, b1 = _bb(o); bpy.data.objects.remove(o, do_unlink=True)   # r8 #13: the 5 m counter -> a 1.8 m console with an orchid
            cx_, cy_ = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
            c_ = ra.abo("console", 91, cx_, cy_, lo[2], math.pi / 2 if (b1[1] - b0[1]) > (b1[0] - b0[0]) else 0.0, fit=(1.8, 0.5, 0.9))
            if c_ is not None:
                ra.abo("bouquet", 92, cx_, cy_, ra.top(c_), 0.0, fit=(0.4, 0.4, 0.55))
        brass = _plain_metal("ir_h5_gold", (0.8, 0.62, 0.25), 0.3); rv = _flat("ir_h5_reveal", (0.03, 0.025, 0.02), 0.5); rp = {rv: [], brass: []}
        for line, side in ((lo[0] + 0.003, 1), (hi[0] - 0.003, -1)):      # r13: break the 7.5 m side walls into 1.25 m book-matched panels: dark reveal + brass strip every 1.25 m, plinth and a brass picture rail
            for yy in [lo[1] + 0.3 + 1.25 * i for i in range(1, int((hi[1] - lo[1]) / 1.25))]:
                if any(a_ - 0.1 < yy < b_ + 0.1 for a_, b_ in _door_gaps(1, line, lo[1], hi[1]) + [(3.4, 4.6)]):
                    continue
                rp[rv].append(("box", line + side * 0.012, yy, 1.7, 0.012, 0.025, ZC - 0.5)); rp[brass].append(("box", line + side * 0.018, yy, 1.7, 0.006, 0.008, ZC - 0.5))
            rp[brass].append(("box", line + side * 0.014, (lo[1] + hi[1]) / 2, 2.55, 0.012, hi[1] - lo[1] - 0.6, 0.03)); rp[rv].append(("box", line + side * 0.014, (lo[1] + hi[1]) / 2, 0.19, 0.016, hi[1] - lo[1] - 0.6, 0.18))
        yv = 8.14 - 0.012                                                  # the hall's north wall = the corridor's walnut veneer seen from the hall side (the 'ochre slab' in wide0 / wide3): same reveals + brass rail
        for xx in [lo[0] + 0.3 + 1.25 * i for i in range(0, int((hi[0] - lo[0]) / 1.25))]:
            if any(a_ - 0.1 < xx < b_ + 0.1 for a_, b_ in _door_gaps(0, 8.14, lo[0], hi[0])):
                continue
            rp[rv].append(("box", xx, yv, 1.7, 0.025, 0.012, ZC - 0.5)); rp[brass].append(("box", xx, yv - 0.006, 1.7, 0.008, 0.006, ZC - 0.5))
        rp[brass].append(("box", (lo[0] + hi[0]) / 2, yv - 0.003, 2.55, hi[0] - lo[0] - 0.6, 0.012, 0.03)); rp[rv].append(("box", (lo[0] + hi[0]) / 2, yv - 0.004, 0.19, hi[0] - lo[0] - 0.6, 0.016, 0.18))
        _emit_mesh("H5ElevReveals", rp)
        _fl().mesh_object("H5ElevBrassBand", [(brass, [("box", (lo[0] + hi[0]) / 2, lo[1] + 0.17, 1.0, hi[0] - lo[0] - 0.2, 0.012, 0.03), ("box", (lo[0] + hi[0]) / 2, lo[1] + 0.17, 0.16, hi[0] - lo[0] - 0.2, 0.012, 0.06)])], bevel=False)
    lo, hi = _room(CORR)
    if lo is not None:
        ven = bpy.data.materials.get("ir_h5_walnut_veneer")
        if ven is None:
            import lux_shell                                          # vertical book-matched leaves: 60 cm wide veneer flitches, straight + cathedral grain, satin
            ven = _flat("ir_h5_walnut_veneer", (0.36, 0.22, 0.13), 0.38); nt = ven.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
            geo = N.new("ShaderNodeNewGeometry"); mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (40.0, 40.0, 1.2); L.new(geo.outputs["Position"], mp.inputs["Vector"])
            wv = N.new("ShaderNodeTexWave"); wv.wave_type = "BANDS"; wv.bands_direction = "X"; wv.inputs["Scale"].default_value = 1.0; wv.inputs["Distortion"].default_value = 3.0; wv.inputs["Detail"].default_value = 4.0
            L.new(mp.outputs["Vector"], wv.inputs["Vector"])
            mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.inputs["A"].default_value = (0.4, 0.25, 0.15, 1); mx.inputs["B"].default_value = (0.22, 0.13, 0.07, 1)
            L.new(wv.outputs["Fac"], mx.inputs["Factor"]); L.new(mx.outputs["Result"], b.inputs["Base Color"])
            bu = N.new("ShaderNodeBump"); bu.inputs["Strength"].default_value = 0.05; bu.inputs["Distance"].default_value = 0.001; L.new(wv.outputs["Fac"], bu.inputs["Height"]); L.new(bu.outputs["Normal"], b.inputs["Normal"])
            b.inputs["Coat Weight"].default_value = 0.3; b.inputs["Coat Roughness"].default_value = 0.2
        n = 0; strips = []
        brass = _flat("ir_h5_gold", (0.8, 0.62, 0.25), 0.3, 1.0)
        for nm in ("H5CorrWoodS", "H5CorrWoodN"):
            o = bpy.data.objects.get(nm)
            if o is None:
                continue
            o.data = o.data.copy()
            for i in range(len(o.data.materials)):
                o.data.materials[i] = ven
            b0, b1 = _bb(o); side = 1 if nm.endswith("S") else -1; yf = (b1[1] if side == 1 else b0[1]) + side * 0.004
            for a, b_ in _segments(lo[0] + 0.1, hi[0] - 0.1, _door_gaps(0, (b0[1] + b1[1]) / 2, lo[0], hi[0])):
                for i in range(1, int((b_ - a) / 0.6)):
                    strips.append(("box", a + i * (b_ - a) / int((b_ - a) / 0.6), yf, (b0[2] + b1[2]) / 2, 0.012, 0.008, b1[2] - b0[2] - 0.02)); n += 1
                strips.append(("box", (a + b_) / 2, yf, 0.95, b_ - a, 0.008, 0.015))
        if strips:
            _fl().mesh_object("H5CorrBrassStrips", [(brass, strips)], bevel=False)
        stats["h5_corr_veneer_strips"] = n


def _curtain(name, mat, x0, x1, y, side, z0, z1, along_x, folds=10, depth=0.06, seed=0):
    """A pleated curtain panel from x0..x1 (along the wall), hanging z0..z1, `side` = which way the room lies; sine pleats + a slight hem flare."""
    rg = random.Random(seed); n_u = folds * 6 + 1; n_v = 24; ph = rg.uniform(0, 6.28)
    def V(i, j):
        u = x0 + (x1 - x0) * i / (n_u - 1); z = z1 - (z1 - z0) * j / (n_v - 1)
        dz = 1.0 + 0.25 * (j / (n_v - 1)) ** 2
        d = side * (0.04 + depth / 2 * math.sin(2 * math.pi * folds * i / (n_u - 1) + ph) * dz)
        return (u, y + d, z) if along_x else (y + d, u, z)
    return _panel_mesh(name, mat, V, n_u, n_v)


def _windows(stats):
    """r9 #8: guest-room windows get depth: a 15 cm bronze-framed reveal, mullion, stone sill, a ceiling curtain track, blackout drapes either side and a half-drawn sheer."""
    fr_ = _flat("ir_h5_winframe", (0.18, 0.15, 0.12), 0.35, 1.0); sill = _veined("ir_h5_sill", (0.86, 0.82, 0.75), (0.7, 0.65, 0.58), 0.6, 0.0005, 0.12)
    drape = _flat("ir_h5_drape", (0.55, 0.5, 0.44), 0.9); sheer = bpy.data.materials.get("ir_h5_sheer")
    if sheer is None:
        sheer = _pa()._flat("ir_h5_sheer", (0.95, 0.94, 0.9), 0.6, 0.0, transmission=0.0); b = sheer.node_tree.nodes["Principled BSDF"]
        b.inputs["Alpha"].default_value = 0.45; sheer.blend_method = "BLEND" if hasattr(sheer, "blend_method") else None; sheer["weathered"] = True
    track = _flat("ir_h5_track", (0.2, 0.2, 0.2), 0.4, 1.0); n = 0
    for f in list(bpy.data.objects):
        if not (f.type == "MESH" and f.name.startswith("bedroom_0/") and f.name.endswith(".floor")):
            continue
        lo, hi = _fbox(f); fz = hi[2]
        for w in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("WindowFactory(")]:
            b0, b1 = _bb(w); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
            along_x = (b1[0] - b0[0]) >= (b1[1] - b0[1])
            if along_x:
                if not (lo[0] - 0.2 < cx < hi[0] + 0.2 and (abs(cy - lo[1]) < 0.4 or abs(cy - hi[1]) < 0.4)):
                    continue
                wall = lo[1] if abs(cy - lo[1]) < 0.4 else hi[1]; side = 1 if wall == lo[1] else -1; a0, a1 = b0[0], b1[0]
            else:
                if not (lo[1] - 0.2 < cy < hi[1] + 0.2 and (abs(cx - lo[0]) < 0.4 or abs(cx - hi[0]) < 0.4)):
                    continue
                wall = lo[0] if abs(cx - lo[0]) < 0.4 else hi[0]; side = 1 if wall == lo[0] else -1; a0, a1 = b0[1], b1[1]
            zb, ztp = b0[2], b1[2]
            def P(a, d, z, sa, sd, sz):
                return ("box", a, wall + side * d, z, sa, sd, sz) if along_x else ("box", wall + side * d, a, z, sd, sa, sz)
            pr = {fr_: [], sill: [], track: []}
            for a in (a0 - 0.04, a1 + 0.04):                         # reveal jambs, 15 cm deep, + head
                pr[fr_].append(P(a, 0.075, (zb + ztp) / 2, 0.06, 0.15, ztp - zb + 0.08))
            pr[fr_].append(P((a0 + a1) / 2, 0.075, ztp + 0.04, a1 - a0 + 0.14, 0.15, 0.06))
            pr[fr_].append(P((a0 + a1) / 2, 0.02, (zb + ztp) / 2, 0.05, 0.05, ztp - zb))     # centre mullion
            pr[sill].append(P((a0 + a1) / 2, 0.13, zb - 0.02, a1 - a0 + 0.3, 0.26, 0.04))
            ta, tb = a0 - 0.7, a1 + 0.7; zt_ = ZC - 0.12
            pr[track].append(P((ta + tb) / 2, 0.22, zt_, tb - ta, 0.05, 0.04))
            _emit_mesh(f"H5Window({f.name[:-6]}|{n})", pr)
            ya = wall + side * 0.22
            _curtain(f"H5DrapeL{n}", drape, ta, a0 + 0.05, ya, side, fz + 0.01, zt_ - 0.02, along_x, folds=6, seed=n)
            _curtain(f"H5DrapeR{n}", drape, a1 - 0.05, tb, ya, side, fz + 0.01, zt_ - 0.02, along_x, folds=6, seed=n + 50)
            _curtain(f"H5Sheer{n}", sheer, a0, a0 + (a1 - a0) * 0.45, wall + side * 0.17, side, fz + 0.02, zt_ - 0.02, along_x, folds=9, depth=0.04, seed=n + 90)
            n += 1
    stats["h5_windows"] = n


def _vary(stats):
    """r9 #2 (kit-stage part): every second guest room is mirrored about its own centre line (whole furniture group incl. en-suite, so the bed moves to the other wall), deterministic by room id;
    only when the room's door sits within 0.45 m of the centre line (so the entry stays clear). The architecture (floor / walls / ceiling / doors / windows) stays."""
    from mathutils import Matrix
    arch = ("door", "DoorCasing", "LiteDoor", "GlassPanelDoor", "PanelDoor", "Window", "window", "Baseboard", "H5Window", "H5Drape", "H5Sheer")
    n = 0
    for f in list(bpy.data.objects):
        if not (f.type == "MESH" and f.name.startswith("bedroom_0/") and f.name.endswith(".floor")):
            continue
        rid = f.name[:-6]; k = int(rid.split("/")[-1])
        if k % 2 == 0:
            continue
        lo, hi = _fbox(f); along_x = (hi[0] - lo[0]) < (hi[1] - lo[1])    # mirror across the short axis's centre: the long room keeps its door / window ends
        c = (lo[0] + hi[0]) / 2 if along_x else (lo[1] + hi[1]) / 2
        doors = [_bb(o) for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("GlassPanelDoor", "LiteDoor", "PanelDoor")) and _in_room(o, (lo[0] - 0.3, lo[1] - 0.3, 0), (hi[0] + 0.3, hi[1] + 0.3, 0))]
        if any(abs(((d[0][0] + d[1][0]) / 2 if along_x else (d[0][1] + d[1][1]) / 2) - c) > 0.45 for d in doors):
            continue
        M = (Matrix.Translation((2 * c, 0, 0)) @ Matrix.Scale(-1, 4, (1, 0, 0))) if along_x else (Matrix.Translation((0, 2 * c, 0)) @ Matrix.Scale(-1, 4, (0, 1, 0)))
        moved = 0
        for o in list(bpy.data.objects):
            if o.parent is not None or o.name.startswith(rid) or o.name.startswith(arch) or o.type not in ("MESH", "LIGHT", "EMPTY", "CURVE"):
                continue
            b0, b1 = _bb(o) if o.type == "MESH" else ((o.matrix_world.translation.x, o.matrix_world.translation.y, 0), (o.matrix_world.translation.x, o.matrix_world.translation.y, 0))
            ox, oy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
            if not (lo[0] + 0.02 < ox < hi[0] - 0.02 and lo[1] + 0.02 < oy < hi[1] - 0.02):
                continue
            o.matrix_world = M @ o.matrix_world; moved += 1
        n += 1; stats.setdefault("h5_vary_rooms", []).append(rid)
    stats["h5_vary"] = n


def _lights(stats):
    stats["h5_lights"] = 1



# ------------------------------------------------------------------------------------------------------ sea view
def _r3_sea(stats):
    """The env-window cards (4 planes outside the glass) and the lounge's sunset panes show a sea instead of the city skyline (refs: every room's window looks onto sea + islands)."""
    day = bpy.data.images.load(rc.sea_panorama("day"), check_existing=True); sun = bpy.data.images.load(rc.sea_panorama("sunset"), check_existing=True); n = 0
    for m in bpy.data.materials:
        if m.use_nodes and m.name.startswith("ir_bg_card_env"):
            for nd in m.node_tree.nodes:
                if nd.type == "TEX_IMAGE":
                    nd.image = day; n += 1
    m = bpy.data.materials.get("ir_h5_sunset")
    if m is not None:
        for nd in m.node_tree.nodes:
            if nd.type == "TEX_IMAGE":
                nd.image = sun; n += 1
            elif nd.type == "MAPPING":
                nd.inputs["Scale"].default_value = (0.32, 0.5, 1.0); nd.inputs["Location"].default_value = (0.1, 0.3, 0.0)
            elif nd.type == "MIX" and nd.blend_type == "MULTIPLY":
                nd.inputs["Factor"].default_value = 0.2
    stats["r3_sea"] = n


# ------------------------------------------------------------------------------------------------------ materials
# ------------------------------------------------------------------------------------------------------ bedroom suite
def _r3_suite(stats, rn="bedroom_0/0"):
    """Guest suite 0/0 (ref guest_room_view1 / view2): a lit metal-and-oak media wall with the TV on the west wall, a window-end lounge (sofa, armchair, round table, floor lamp, triptych), a large pale
    ribbed rug under the bed, a ceiling fan. The old TV / credenza / bookcase / mirror / patterned rug go."""
    lo, hi = _wall_face().inner_box(rn)
    if lo is None:
        return
    z0 = lo[2]; x0, x1 = lo[0], hi[0]; y1 = hi[1]
    _rm_in((x0 - 0.1, 11.5), (x1 + 0.1, y1 + 0.1), ("Real_credenza", "Real_tv", "AboBookcaseFactory", "H5BedMirror", "Real_bigrug", "Real_wallart"))
    # (the headboard print is a Real_wallart too: it is re-hung below)
    oak = _wood("ir_h5_oak", (0.62, 0.45, 0.28)); dkm = _plain_metal("ir_r3_darkmetal", (0.05, 0.05, 0.055), 0.4); led = _emit("ir_r3_led", (1.0, 0.8, 0.5), 7.0)
    cab = _flat("ir_r3_cab", (0.17, 0.13, 0.1), 0.45); cream = _flat("ir_r3_panel", (0.86, 0.8, 0.7), 0.9)
    pr = {m: [] for m in (oak, dkm, led, cab, cream)}
    ya, yb, yc, yd = 11.75, 12.85, 15.05, 16.15                         # side bay A, TV bay, side bay B
    xs = x0 + 0.16; dep = 0.32; H = 2.5
    for y_ in (ya, yb, yc, yd):
        pr[dkm].append(("box", x0 + dep / 2, y_, z0 + H / 2, dep, 0.035, H))                          # steel posts
    pr[oak].append(("box", x0 + 0.02, (yb + yc) / 2, z0 + H / 2, 0.04, yc - yb, H))                    # oak-veneer back of the TV bay
    shelves = (0.55, 0.95, 1.35, 1.75, 2.15, 2.5)
    for (a, b_) in ((ya, yb), (yc, yd)):
        w = b_ - a - 0.035; yc_ = (a + b_) / 2
        pr[cream].append(("box", x0 + 0.015, yc_, z0 + H / 2, 0.03, w, H))
        pr[cab].append(("box", x0 + dep / 2 + 0.005, yc_, z0 + 0.27, dep - 0.02, w, 0.5))              # base cupboard
        for zz in shelves[1:]:
            pr[oak].append(("box", xs, yc_, z0 + zz, dep - 0.02, w, 0.03)); pr[led].append(("box", x0 + dep - 0.04, yc_, z0 + zz - 0.022, 0.012, w - 0.03, 0.008))
    pr[oak].append(("box", xs, (yb + yc) / 2, z0 + 2.15, dep - 0.02, yc - yb, 0.03)); pr[led].append(("box", x0 + dep - 0.04, (yb + yc) / 2, z0 + 2.15 - 0.022, 0.012, yc - yb - 0.03, 0.008))
    pr[led].append(("box", x0 + 0.05, (yb + yc) / 2, z0 + 0.62, 0.012, yc - yb - 0.03, 0.008))
    _emit_mesh("H5R3MediaWall", pr)
    for zz in (1.0, 1.9):
        _light("ir_r3_shelf_%d" % int(zz * 10), "AREA", (x0 + 0.3, 13.8, z0 + zz + 0.35), 40, (1.0, 0.78, 0.5), sx=0.2, sy=4.0)
    rc.pool("r3_cred", "credenza", r"Alexandra|Wyatt|Larkin|Hollis|Apsley|Coby")
    cr = rc.place("r3_cred", 31, x0 + 0.30, (yb + yc) / 2, z0, 0.0, (2.0, 0.46, 0.62), "Real_r3_credenza")
    zt_c = ra.top(cr) if cr is not None else z0 + 0.55
    tv = rc.tv(32, x0 + 0.06, (yb + yc) / 2, z0 + 0.98, 0.0, (1.55, 0.2, 0.92), "Real_r3_tv")
    stats["r3_tv_dims"] = [round(v, 2) for v in tv.dimensions] if tv is not None else None
    # shelf contents: books, bowls, vases, plants (real models)
    rg = random.Random(5); k = 0
    for (a, b_) in ((ya, yb), (yc, yd)):
        for zz in shelves[:-1]:
            zb_ = z0 + (0.52 if zz == 0.55 else zz) + 0.015
            if zz == 0.55:
                zb_ = z0 + 0.52
            for j in range(rg.choice((2, 3))):
                yy = a + 0.14 + (b_ - a - 0.28) * (j + rg.uniform(0.1, 0.9)) / 3; k += 1
                kind = rg.choice(("book", "book", "vase", "bowl", "plant"))
                if kind == "book":
                    for q in range(rg.choice((2, 3))):
                        o = ra.abo("book", k * 7 + q, xs, yy, zb_ + q * 0.03, math.pi / 2 + rg.uniform(-0.1, 0.1), fit=(0.26, 0.2, 0.03 if rg.random() < 0.6 else 0.22))
                        if o is not None:
                            o.name = "Real_r3_book"
                elif kind == "vase":
                    o = ra.lib("VaseFactory", k, xs, yy, zb_, 0.0, 0.7)
                    if o is not None:
                        o.name = "Real_r3_vase"
                elif kind == "bowl":
                    o = ra.lib("BowlFactory", k, xs, yy, zb_, 0.0, 0.8)
                    if o is not None:
                        o.name = "Real_r3_bowl"
                else:
                    o = ra.abo("smallplant", k, xs, yy, zb_, rg.uniform(0, 6.28), fit=(0.25, 0.22, 0.34))
                    if o is not None:
                        o.name = "Real_r3_plant"
    for yy in (12.3, 15.6):                                              # trailing plants on top
        o = ra.abo("smallplant", int(yy * 10), xs, yy, z0 + 2.5 + 0.015, 0.0, fit=(0.32, 0.3, 0.45))
        if o is not None:
            o.name = "Real_r3_plant_top"
    for yy, dz in ((14.4, 0.0), (15.0, 0.0)):                            # credenza top
        pass
    rc.place("smallplant", 77, x0 + 0.3, 14.95, zt_c, 0.0, (0.3, 0.3, 0.38), "Real_r3_plant_cred")
    # window-end lounge
    rc.ids_pool("r3_loveseat", ("B07B4P4M31", "B07QBMQC7M"))
    rc.ids_pool("r3_arm", ("B082QBZB1Q", "B07FJWDWBV", "B082QBH69W"))
    rc.pool("r3_lamp", "floorlamp", r"ivory|beige|white|linen|fabric|shade|tripod|stacked", y=(1.4, 1.75))
    rc.pool("r3_round", "roundtable", None)
    stats["r3_pools"] = {k_: len(ra._POOLS[k_]) for k_ in ("r3_loveseat", "r3_arm", "r3_lamp", "r3_round")}
    sofa = rc.place("r3_loveseat", 41, x1 - 0.52, 19.45, z0, math.pi, (2.05, 0.95, 0.95), "Real_r3_sofa")
    rc.place("r3_arm", 42, 12.35, 20.7, z0, math.atan2(-1.0, 0.35), (0.9, 0.9, 0.95), "Real_r3_arm")
    tb = rc.place("r3_round", 43, 12.55, 19.35, z0, 0.0, (0.85, 0.85, 0.5), "Real_r3_table")
    zt_t = ra.top(tb) if tb is not None else z0 + 0.45
    rc.place("r3_lamp", 44, x1 - 0.3, 21.4, z0, 0.0, (0.42, 0.42, 1.65), "Real_r3_lamp")
    ra.abo("smallplant", 45, 12.55, 19.4, zt_t, 0.0, fit=(0.3, 0.3, 0.35))
    o = ra.abo("book", 46, 12.4, 19.2, zt_t, 0.4, fit=(0.28, 0.2, 0.05))
    if o is not None:
        o.name = "Real_r3_book"
    for j, yy in enumerate((18.6, 19.45, 20.3)):                         # coordinated triptych over the sofa
        o = ra.abo("wallart", 4242, x1 - 0.03, yy, z0 + 1.15, math.pi, fit=(0.55, 0.05, 0.8))
        if o is not None:
            o.name = "Real_r3_art"
    o = ra.abo("wallart", 5151, x1 - 0.03, 16.5, z0 + 1.42, math.pi, fit=(1.2, 0.05, 0.8))               # over the headboard
    if o is not None:
        o.name = "Real_r3_art_head"
    # rug
    rm = rc.rug_mat(); pr = {rm: [("box", 11.95, 16.4, z0 + 0.012, 3.1, 3.9, 0.022)]}
    _emit_mesh("H5R3Rug", pr)
    # ceiling fan
    rc.hs(r"Cirrus Ceiling Fan$|Aeroplan 3 Blade", 3, 12.25, 13.9, 3.65 - 0.4, 0.0, (1.3, 1.3, 0.4), "Real_r3_fan")
    stats["r3_suite"] = 1


# ------------------------------------------------------------------------------------------------------ sky lounge
def _r3_lounge(stats):
    """Ref sky_lounge: large grey curved-back sofas round dark low round tables on big pale round rugs, low grey club chairs, window-side dining-height round tables with chairs, tall palms in square
    planters, books / bowls / plants on the coffee tables, smooth champagne columns."""
    lo, hi = _room(LOUNGE)
    if lo is None:
        return
    z0 = lo[2]
    _rm_in(lo, hi, ("Real_loungesofa", "Real_bigrug", "Real_roundtable", "Real_coffee", "Real_barrel", "Real_smallplant", "VaseFactory"))
    col = bpy.data.objects.get("H5LoungeColumns")
    if col is not None:
        cm = _plain_metal("ir_r3_champagne", (0.62, 0.5, 0.37), 0.28, 0.4)
        col.data.materials[0] = cm
        for pgn in col.data.polygons:
            pgn.use_smooth = True
    rug = rc.rug_mat("ir_r3_round_rug", (0.84, 0.8, 0.72), stripes=False)
    rc.ids_pool("r3_lsofa", ("B07B4MF6S6", "B082Q9C9YJ", "B07QCMBHN2"))
    rc.ids_pool("r3_club", ("B082QBH69W", "B082QCB52Z", "B082Q97X2R"))
    rc.pool("r3_dtab", "roundtable", r"Artum|Cinder")
    stats["r3_lounge_pools"] = {k: len(ra._POOLS[k]) for k in ("r3_lsofa", "r3_club", "r3_dtab")}
    groups = [(2.6, 11.9, 0.0), (2.6, 18.1, 0.0), (8.2, 15.0, math.pi)]
    pr = {rug: []}
    for gi, (gx, gy, rot) in enumerate(groups):
        fx, fy = math.cos(rot), math.sin(rot)
        pr[rug].append(("cyl", (gx - fx * 0.3, gy - fy * 0.3, z0 + 0.0), (gx - fx * 0.3, gy - fy * 0.3, z0 + 0.022), 1.9, 64))
        sofa = rc.place("r3_lsofa", 211 + gi, gx - fx * 1.3, gy - fy * 1.3, z0 + 0.02, rot, (3.0, 1.1, 0.95), "Real_r3_lsofa")
        tb = rc.place("r3_dtab", 221 + gi, gx, gy, z0 + 0.02, 0.0, (1.15, 1.15, 0.5), "Real_r3_ltable")
        zt = ra.top(tb) if tb is not None else z0 + 0.45
        for q, (kind, dx, dy) in enumerate((("book", -0.18, 0.1), ("book", -0.16, 0.12), ("plant", 0.2, -0.1), ("bowl", 0.0, -0.25))):
            if kind == "book":
                o = ra.abo("book", 300 + gi * 5 + q, gx + dx, gy + dy, zt + (0.03 if q else 0.0), 0.3 * q, fit=(0.28, 0.2, 0.04))
            elif kind == "plant":
                o = ra.abo("smallplant", 310 + gi, gx + dx, gy + dy, zt, 0.0, fit=(0.3, 0.3, 0.38))
            else:
                o = ra.lib("BowlFactory", 320 + gi, gx + dx, gy + dy, zt, 0.0, 0.7)
            if o is not None:
                o.name = "Real_r3_ldecor"
        for sgn in (-1, 1):
            a = rot + sgn * 0.75; px, py = gx + math.cos(a) * 1.3, gy + math.sin(a) * 1.3
            rc.place("r3_club", 231 + gi * 2 + (sgn > 0), px, py, z0 + 0.02, a + math.pi, (0.95, 0.95, 0.85), "Real_r3_club")
    _emit_mesh("H5R3LoungeRugs", pr)
    # window-side dining-height round tables + chairs, along the north window
    wood = _wood("ir_h5_oak", (0.62, 0.45, 0.28)); brass = _flat("ir_h5_brass", (0.72, 0.52, 0.22), 0.3, 1.0); cloth = _flat("ir_r3_dine_top", (0.12, 0.09, 0.07), 0.25)
    pr = {wood: [], brass: [], cloth: []}
    rc.pool("r3_dchair", "deskchair", r"Dining|Wishbone|Lamberton|Scarlett|Hallaway|Lorna|Jane|Wendy", x=(0.44, 0.62))
    for ti, (tx, ty) in enumerate(((3.6, 20.7), (6.1, 20.35), (8.7, 20.35))):
        pr[cloth].append(("cyl", (tx, ty, z0 + 0.72), (tx, ty, z0 + 0.755), 0.5, 40)); pr[brass].append(("cyl", (tx, ty, z0), (tx, ty, z0 + 0.72), 0.04, 16)); pr[brass].append(("cyl", (tx, ty, z0), (tx, ty, z0 + 0.025), 0.28, 32))
        o = ra.lib("VaseFactory", 340 + ti, tx, ty, z0 + 0.755, 0.0, 0.6)
        if o is not None:
            o.name = "Real_r3_dvase"
        o = ra.abo("smallplant", 350 + ti, tx + 0.1, ty, z0 + 0.755, 0.0, fit=(0.22, 0.22, 0.3))
        if o is not None:
            o.name = "Real_r3_dplant"
        for q in range(4):
            a = q * math.pi / 2 + 0.4 + ti
            rc.place("r3_dchair", 360 + ti * 4 + q, tx + math.cos(a) * 0.72, ty + math.sin(a) * 0.72, z0 + 0.02, a + math.pi, (0.55, 0.55, 0.95), "Real_r3_dchair")
    _emit_mesh("H5R3DiningTables", pr)
    # palms in square planters
    plm = _flat("ir_r3_planter", (0.1, 0.1, 0.1), 0.35, 0.6); pr = {plm: []}
    for pi_, (px, py) in enumerate(((0.9, 15.0), (4.9, 21.1), (9.3, 11.5))):
        pr[plm].append(("box", px, py, z0 + 0.275, 0.72, 0.72, 0.55)); pr[plm].append(("box", px, py, z0 + 0.57, 0.78, 0.78, 0.04))
        rc.plant("atrium", 400 + pi_, px, py, z0 + 0.55, 2.3, 1.3, yaw=pi_ * 1.3, name="Real_r3_palm")
    _emit_mesh("H5R3Planters", pr)
    stats["r3_lounge"] = 1


# ------------------------------------------------------------------------------------------------------ shared small builders
# ------------------------------------------------------------------------------------------------------ lift hall
def _r3_elev(stats):
    """Ref elevator_hall: cream stone floor with big dark mauve cloud inlays, lit leafy recesses, broad dark stone console with a long low flower arrangement, a rectangular lit tray in the ceiling, vertical warm back-light strips on the panelling."""
    lo, hi = _room(ELEV)
    if lo is None:
        return
    z0 = lo[2]
    _set_floor(ELEV, _noise_mix("ir_r3_elev_floor", (0.88, 0.83, 0.74), (0.34, 0.22, 0.21), 0.42, rough=0.07, detail=2.0, distort=3.2))
    for nm in ("H5ElevPlantNiches",):
        o = bpy.data.objects.get(nm)
        if o is not None:
            bpy.data.objects.remove(o, do_unlink=True)
    _rm_in(lo, hi, ("Real_smallplant", "Real_bouquet", "Real_console"))
    mats, pr = rc.niche_pr(); n = 0
    for k, (axis, line, side, u) in enumerate(((0, lo[1] + 0.2, 1, 12.8), (0, lo[1] + 0.2, 1, 17.2), (1, hi[0] - 0.02, -1, 1.7), (1, hi[0] - 0.02, -1, 6.3))):
        n += rc.green_niche(pr, mats, axis, line, side, u, seed=50 + k)
    _emit_mesh("H5R3ElevNiches", pr)
    # console: dark veined stone slab on two brass-capped plinths + a long low arrangement (3 bud vases of white / pink blooms, a trough of ferns)
    stone = _veined("ir_r3_dark_stone", (0.08, 0.07, 0.07), (0.62, 0.5, 0.38), 0.9, 0.0, 0.1, vein_scale=3.0); brass = _flat("ir_h5_gold", (0.8, 0.62, 0.25), 0.3, 1.0)
    cx, cy = lo[0] + 0.3, 4.0; pr = {stone: [("box", cx, cy, z0 + 0.82, 0.42, 1.9, 0.06), ("box", cx - 0.02, cy - 0.8, z0 + 0.4, 0.3, 0.2, 0.8), ("box", cx - 0.02, cy + 0.8, z0 + 0.4, 0.3, 0.2, 0.8), ("box", cx - 0.02, cy, z0 + 0.5, 0.3, 1.4, 0.04)], brass: [("box", cx - 0.02, cy, z0 + 0.1, 0.32, 1.9, 0.02)]}
    _emit_mesh("H5R3Console", pr)
    for j, dy in enumerate((-0.6, -0.2, 0.2, 0.6)):
        rc.bouquet(70 + j, cx, cy + dy, z0 + 0.85, 0.75 if j % 2 else 0.55, big=bool(j % 2))
    # ceiling tray
    cream = _flat("ir_h5_ceil", (0.9, 0.88, 0.84), 0.6); cove = _emit("ir_h5_cove", (1.0, 0.78, 0.5), 3.0)
    tx0, tx1, ty0, ty1 = 12.2, 17.8, 1.9, 6.4; tz = 3.65
    pr = {cream: [("box", (tx0 + tx1) / 2, ty0, tz - 0.07, tx1 - tx0, 0.22, 0.14), ("box", (tx0 + tx1) / 2, ty1, tz - 0.07, tx1 - tx0, 0.22, 0.14), ("box", tx0, (ty0 + ty1) / 2, tz - 0.07, 0.22, ty1 - ty0, 0.14), ("box", tx1, (ty0 + ty1) / 2, tz - 0.07, 0.22, ty1 - ty0, 0.14)],
          cove: [("box", (tx0 + tx1) / 2, ty0 + 0.125, tz - 0.015, tx1 - tx0 - 0.4, 0.03, 0.02), ("box", (tx0 + tx1) / 2, ty1 - 0.125, tz - 0.015, tx1 - tx0 - 0.4, 0.03, 0.02), ("box", tx0 + 0.125, (ty0 + ty1) / 2, tz - 0.015, 0.03, ty1 - ty0 - 0.4, 0.02), ("box", tx1 - 0.125, (ty0 + ty1) / 2, tz - 0.015, 0.03, ty1 - ty0 - 0.4, 0.02)]}
    _emit_mesh("H5R3ElevTray", pr)
    # vertical back-light strips beside the panel reveals on the side walls
    led = _emit("ir_r3_led", (1.0, 0.8, 0.5), 7.0); pr = {led: []}
    for line, side in ((lo[0] + 0.003, 1), (hi[0] - 0.003, -1)):
        gaps = _door_gaps(1, line, lo[1], hi[1]) + [(3.4, 4.6)]
        for yy in [lo[1] + 0.3 + 1.25 * i + 0.04 for i in range(1, int((hi[1] - lo[1]) / 1.25))]:
            if any(a_ - 0.1 < yy < b_ + 0.1 for a_, b_ in gaps):
                continue
            pr[led].append(("box", line + side * 0.03, yy, 1.7, 0.012, 0.025, ZC - 0.7))
    _emit_mesh("H5R3ElevStrips", pr)
    stats["r3_elev"] = {"niche_plants": n}


# ------------------------------------------------------------------------------------------------------ guest corridor
def _r3_corr(stats):
    """Ref guest_corridor: big cream / brown cloud carpet, repeated lit green planting panels, pale timber panelling, repeated lit inset rectangular ceiling bays."""
    lo, hi = _room(CORR)
    if lo is None:
        return
    z0 = lo[2]
    m = _noise_mix("ir_r3_corr_carpet", (0.86, 0.8, 0.7), (0.36, 0.26, 0.24), 0.38, rough=0.95, detail=3.0, distort=2.4)
    if not m.get("r3_pile"):
        nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]; pile = N.new("ShaderNodeTexNoise"); pile.inputs["Scale"].default_value = 420.0
        tc = N.new("ShaderNodeTexCoord"); L.new(tc.outputs["Object"], pile.inputs["Vector"]); bu = N.new("ShaderNodeBump"); bu.inputs["Strength"].default_value = 0.25; bu.inputs["Distance"].default_value = 0.002
        L.new(pile.outputs["Fac"], bu.inputs["Height"]); L.new(bu.outputs["Normal"], b.inputs["Normal"]); m["r3_pile"] = 1
    _set_floor(CORR, m)
    ven = bpy.data.materials.get("ir_h5_walnut_veneer")
    if ven is not None and not ven.get("r3_pale"):
        for nd in ven.node_tree.nodes:
            if nd.type == "MIX" and nd.data_type == "RGBA":
                nd.inputs["A"].default_value = (0.76, 0.62, 0.45, 1); nd.inputs["B"].default_value = (0.62, 0.49, 0.34, 1)
        ven["r3_pale"] = 1
    for nm in ("H5CorrPlantNiches",):
        o = bpy.data.objects.get(nm)
        if o is not None:
            bpy.data.objects.remove(o, do_unlink=True)
    _rm_in(lo, hi, ("Real_smallplant",))
    x0, x1 = lo[0] + 0.1, hi[0] - 0.1; sb = 0.55; mats, pr = rc.niche_pr(); nn = 0
    for line, side in ((lo[1] + 0.05, 1), (hi[1] - 0.05, -1)):
        gaps = _door_gaps(0, line, x0, x1)
        for i, (a, b_) in enumerate(_segments(x0, x1, gaps, 1.4)):
            if i % 2 == 0:
                nn += rc.green_niche(pr, mats, 0, line + side * 0.04, side, (a + b_) / 2, w=min(0.85, b_ - a - 0.4), seed=100 + nn)
    _emit_mesh("H5R3CorrNiches", pr)
    cream = _flat("ir_h5_ceil", (0.9, 0.88, 0.84), 0.6); pan = _emit("ir_r3_bay", (1.0, 0.82, 0.58), 5.0); pr = {cream: [], pan: []}; tz = 3.65; yc = (lo[1] + hi[1]) / 2
    for xc in [x0 + 2.0 + 3.6 * i for i in range(int((x1 - x0 - 2.0) / 3.6))]:
        bw, bl = 1.05, 2.3
        for dx, dy, sx, sy in ((0, bw / 2, bl + 0.16, 0.08), (0, -bw / 2, bl + 0.16, 0.08), (bl / 2, 0, 0.08, bw), (-bl / 2, 0, 0.08, bw)):
            pr[cream].append(("box", xc + dx, yc + dy, tz - 0.05, sx, sy, 0.1))
        pr[pan].append(("box", xc, yc, tz - 0.012, bl - 0.04, bw - 0.1, 0.01))
    _emit_mesh("H5R3CorrBays", pr)
    stats["r3_corr"] = {"niches": nn}


# ------------------------------------------------------------------------------------------------------ banquet lobby
def _r3_lobby(stats):
    """Ref banquet_lobby: dark marble reception counter with two lamps and a tall flower display, navy club chairs round floral tables, blue / gold inlay border on top of the floor, gold coffered ceiling, tall sea window, sconces."""
    lo, hi = _room(LOBBY)
    if lo is None:
        return
    z0 = lo[2]
    o = bpy.data.objects.get("H5LobbyInlay")
    if o is not None and not o.get("r3_up"):
        o.location.z += 0.004; o["r3_up"] = 1
    _rm_in(lo, hi, ("AboArmchairFactory", "AboCoffeeFactory", "Real_armchair", "Real_sidetable"))
    for o in [o for o in bpy.data.objects if o.name.startswith("ReceptionDeskFactory") and _in_room(o, lo, hi)]:
        dm = _veined("ir_r3_dark_marble", (0.07, 0.065, 0.065), (0.7, 0.58, 0.42), 0.9, 0.0, 0.08, vein_scale=3.0)
        o.data = o.data.copy()
        for i in range(len(o.data.materials)):
            o.data.materials[i] = dm
        b0, b1 = _bb(o); cx, cy, zt = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2, b1[2]
        for j, dy in enumerate((-1.0, 1.0)):
            rc.place("tablelamp", 600 + j, cx, cy + dy, zt, 0.0, (0.4, 0.4, 0.62), "Real_r3_desklamp")
        rc.bouquet(610, cx, cy, zt, 1.0, big=True)
    rc.ids_pool("r3_navy", ("B072JG3WK1", "B073ZNVMT1")); rc.ids_pool("r3_dtab2", ("B07R8WD99Z",))
    for gi, (gx, gy) in enumerate(((49.4, 3.4), (49.4, 7.2))):
        tb = rc.place("r3_dtab2", 620 + gi, gx, gy, z0, 0.0, (0.9, 0.9, 0.5), "Real_r3_ltable")
        zt = ra.top(tb) if tb is not None else z0 + 0.45
        rc.bouquet(630 + gi, gx, gy, zt, 0.7, big=False)
        for sgn in (-1, 1):
            rc.place("r3_navy", 640 + gi * 2 + (sgn > 0), gx - 0.9, gy + sgn * 0.65, z0, math.atan2(-sgn * 0.65, 0.9), (0.8, 0.8, 0.9), "Real_r3_navy")
    gold = _flat("ir_h5_gold", (0.8, 0.62, 0.25), 0.3, 1.0); pr = {gold: []}
    for yy in (2.7, 5.5, 8.3):
        pr[gold].append(("box", (lo[0] + hi[0]) / 2, yy, ZC - 0.04, hi[0] - lo[0] - 0.4, 0.1, 0.08))
    for xx in (47.6, 50.5, 53.0):
        pr[gold].append(("box", xx, (lo[1] + hi[1]) / 2, ZC - 0.04, 0.1, hi[1] - lo[1] - 0.4, 0.08))
    brass = _flat("ir_h5_brass_w", (0.74, 0.55, 0.24), 0.3, 1.0); shade = _emit("ir_h5_shade", (1.0, 0.86, 0.66), 3.0); pr[brass] = []; pr[shade] = []
    for k, yy in enumerate((1.6, 6.0, 8.0)):
        rc.sconce(pr, brass, shade, lo[0] + 0.01, yy, z0 + 1.9, 1.0, 0.0, f"ir_r3_lsc_{k}")
    _emit_mesh("H5R3LobbyCoffer", pr)
    _sunset("H5R3LobbySea", 0, lo[1] + 0.03, 48.0, 52.6, 0.15, 3.4, 1)
    stats["r3_lobby"] = 1


# ------------------------------------------------------------------------------------------------------ banquet hall
def _r3_hall(stats):
    """Ref banquet_hall: sea-view window bays with curtains, dense luminous crystal chandeliers, big white / green floral centrepieces, tall palms in planters, gilded wall panels with sconces,
    a deeper gold-trimmed coffer, blue-grey / gold swirl carpet."""
    lo, hi = _room(HALL)
    if lo is None:
        return
    z0 = lo[2]
    # carpet: blue-grey / gold
    m = bpy.data.materials.get("ir_h5_banq_carpet")
    if m is not None and not m.get("r3_blue"):
        for nd in m.node_tree.nodes:
            if nd.type == "VALTORGB":
                el = nd.color_ramp.elements
                for e in el:
                    c = e.color; lum = (c[0] + c[1] + c[2]) / 3
                    e.color = (0.52, 0.58, 0.68, 1) if lum < 0.36 else ((0.86, 0.72, 0.46, 1) if lum > 0.62 else (0.66, 0.7, 0.76, 1))
        m["r3_blue"] = 1
    # windows
    ya = hi[1] - 0.06
    _sunset("H5R3HallSea", 0, ya, 46.7, 57.4, 0.15, 3.3, -1)               # one continuous glazed sea wall (the generated window sits behind it)
    drape = _flat("ir_h5_drape", (0.8, 0.7, 0.52), 0.9)
    for k, c0 in enumerate((46.6, 49.2, 51.7, 54.2, 56.6)):
        _curtain(f"H5R3Curtain{k}", drape, c0, c0 + 0.85, ya - 0.1, -1, z0 + 0.01, ZC - 0.1, True, folds=5, depth=0.07, seed=k)
        _curtain(f"H5R3CurtainB{k}", drape, c0 + 0.85, c0 + 1.7, ya - 0.1, -1, z0 + 0.01, ZC - 0.1, True, folds=5, depth=0.07, seed=k + 9)
    # centrepieces
    _rm_in(lo, hi, ("Real_bouquet",))
    for o in [o for o in bpy.data.objects if o.name.startswith("H5Tablecloth")]:
        b0, b1 = _bb(o); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
        if lo[0] < cx < hi[0] and lo[1] < cy < hi[1]:
            rc.bouquet(800 + int(cx * 7 + cy), cx, cy, b1[2], 1.25, big=True)
    # chandeliers: dense luminous spheres
    for o in [o for o in bpy.data.objects if o.name.startswith("H5CrystalChandelier")]:
        b0, b1 = _bb(o); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
        bpy.data.objects.remove(o, do_unlink=True)
        _r3_ball(f"H5R3Chandelier{int(cx)}", cx, cy, ZC - 1.0)
    # extra lit chandeliers over the free thirds
    # blue satin sashes tied on every chair back
    import bmesh
    sash = _flat("ir_h5_sash", (0.12, 0.22, 0.5), 0.35); sash["r3"] = 1; b_ = sash.node_tree.nodes["Principled BSDF"]; b_.inputs["Sheen Weight"].default_value = 0.6
    tabs = []
    for o in bpy.data.objects:
        if o.name.startswith("H5Tablecloth"):
            b0, b1 = _bb(o); tabs.append(((b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2))
    bm_s = bmesh.new(); nsash = 0
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name.startswith("Real_hssd") and tabs:
            b0, b1 = _bb(o); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
            if not (lo[0] < cx < hi[0] and lo[1] < cy < hi[1]) or b0[2] > 0.3 or not (0.7 < b1[2] < 1.2):
                continue
            tx, ty = min(tabs, key=lambda t_: (t_[0] - cx) ** 2 + (t_[1] - cy) ** 2)
            ux, uy = cx - tx, cy - ty; dd = math.hypot(ux, uy) or 1.0; ux, uy = ux / dd, uy / dd
            yaw = math.atan2(uy, ux) + math.pi / 2
            px, py = cx + ux * ((b1[0] - b0[0]) * 0.5 * abs(ux) + (b1[1] - b0[1]) * 0.5 * abs(uy) + 0.01), cy + uy * ((b1[0] - b0[0]) * 0.5 * abs(ux) + (b1[1] - b0[1]) * 0.5 * abs(uy) + 0.01)
            _bow(bm_s, px, py, 0.62, yaw, 0); nsash += 1
            r_ = bmesh.ops.create_cube(bm_s, size=1.0); vs = r_["verts"]; bmesh.ops.scale(bm_s, vec=(0.42, 0.012, 0.09), verts=vs)
            from mathutils import Matrix as _M
            bmesh.ops.rotate(bm_s, cent=(0, 0, 0), matrix=_M.Rotation(yaw, 3, "Z"), verts=vs); bmesh.ops.translate(bm_s, vec=(px - ux * 0.01, py - uy * 0.01, 0.62), verts=vs)
    if nsash:
        me = bpy.data.meshes.new("H5R3Sashes"); bm_s.to_mesh(me); me.materials.append(sash)
        for p_ in me.polygons:
            p_.use_smooth = True
        bpy.context.scene.collection.objects.link(bpy.data.objects.new("H5R3Sashes", me))
    bm_s.free()
    # palms
    plm = _flat("ir_r3_planter", (0.1, 0.1, 0.1), 0.35, 0.6); pr = {plm: []}
    for pi_, (px, py) in enumerate(((50.55, 21.15), (53.2, 21.15))):
        pr[plm].append(("box", px, py, z0 + 0.275, 0.72, 0.72, 0.55)); pr[plm].append(("box", px, py, z0 + 0.57, 0.78, 0.78, 0.04))
        rc.plant("atrium", 500 + pi_, px, py, z0 + 0.55, 2.2, 1.2, yaw=pi_ * 1.7, name="Real_r3_palm")
    brass = _flat("ir_h5_brass_w", (0.74, 0.55, 0.24), 0.3, 1.0); shade = _emit("ir_h5_shade", (1.0, 0.86, 0.66), 3.0); dark = _flat("ir_r3_smoke", (0.16, 0.12, 0.09), 0.2, 0.3)
    xw = hi[0] - 0.02
    for k, yy in enumerate((12.8, 14.2, 18.2, 19.8)):
        pr.setdefault(brass, []); pr.setdefault(shade, []); pr.setdefault(dark, [])
        pr[brass] += [("box", xw - 0.03, yy, 1.7, 0.04, 0.9, 2.9), ]
        pr[dark] += [("box", xw - 0.055, yy, 1.7, 0.02, 0.78, 2.78)]
    for k, yy in enumerate((13.4, 19.0)):
        rc.sconce(pr, brass, shade, xw, yy, 2.0, -1.0, 0.0, f"ir_r3_hsc_{k}")
    _emit_mesh("H5R3HallDecor", pr)
    # deeper coffer: a second gold-trimmed step under the beams
    W, D = hi[0] - lo[0], hi[1] - lo[1]; gold = _flat("ir_h5_gold", (0.8, 0.62, 0.25), 0.3, 1.0); cream = _flat("ir_h5_ceil", (0.9, 0.88, 0.84), 0.6); pr = {gold: [], cream: []}
    for i in range(1, 3):
        pr[cream].append(("box", lo[0] + W * i / 3, (lo[1] + hi[1]) / 2, ZC - 0.27, 0.5, D, 0.14)); pr[gold].append(("box", lo[0] + W * i / 3, (lo[1] + hi[1]) / 2, ZC - 0.35, 0.52, D, 0.015))
    for j in range(1, 2):
        pr[cream].append(("box", (lo[0] + hi[0]) / 2, lo[1] + D * j / 2, ZC - 0.265, W, 0.5, 0.13)); pr[gold].append(("box", (lo[0] + hi[0]) / 2, lo[1] + D * j / 2, ZC - 0.358, W, 0.52, 0.015))
    _emit_mesh("H5R3HallCoffer", pr)
    stats["r3_hall"] = 1


def _r3_ball(name, cx, cy, zc, nstr=170):
    """Dense spherical crystal chandelier: brass canopy / hub, `nstr` radial strands with bead strings and teardrops, a warm glowing core."""
    import bmesh
    brass = _flat("ir_h5_chand_brass", (0.75, 0.58, 0.28), 0.25, 1.0); crys = bpy.data.materials.get("ir_h5_crystal_glass")
    core = _emit("ir_r3_core", (1.0, 0.72, 0.4), 0.9)
    bm = bmesh.new(); rg = random.Random(int(cx * 10 + cy))
    def cyl(p0, p1, r, seg=6, mi=0):
        d = Vector(p1) - Vector(p0); L = d.length
        if L < 1e-5:
            return
        res = bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r, radius2=r, depth=L)
        bmesh.ops.transform(bm, matrix=d.to_track_quat("Z", "Y").to_matrix().to_4x4(), verts=res["verts"]); bmesh.ops.translate(bm, vec=(Vector(p0) + Vector(p1)) / 2, verts=res["verts"])
        for f in {f for v in res["verts"] for f in v.link_faces}:
            f.material_index = mi
    def bead(c, r, sz=1.0, mi=1):
        res = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=r); bmesh.ops.scale(bm, vec=(1, 1, sz), verts=res["verts"]); bmesh.ops.translate(bm, vec=c, verts=res["verts"])
        for f in {f for v in res["verts"] for f in v.link_faces}:
            f.material_index = mi
    hub = Vector((cx, cy, zc)); cyl((cx, cy, 3.62), hub, 0.012, 8, 0); cyl((cx, cy, 3.62), (cx, cy, 3.5), 0.1, 16, 0)
    res = bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=0.22); bmesh.ops.translate(bm, vec=hub, verts=res["verts"])
    for f in {f for v in res["verts"] for f in v.link_faces}:
        f.material_index = 2
    for k in range(nstr):
        z_ = rg.uniform(-0.95, 0.95); az = rg.uniform(0, 2 * math.pi); r_ = math.sqrt(1 - z_ * z_)
        d = Vector((r_ * math.cos(az), r_ * math.sin(az), z_)); L = rg.uniform(0.55, 0.95)
        tip = hub + d * L; cyl(hub + d * 0.28, tip, 0.003, 5, 0)
        for t in range(1, 8):
            bead(hub + d * (0.28 + (L - 0.28) * t / 8.0), 0.008 + 0.003 * (t % 2), 1.0, 1)
        bead(tip, 0.016, 1.7, 1)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free(); me.materials.append(brass); me.materials.append(crys); me.materials.append(core)
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    _light(f"ir_r3_chl_{name}", "POINT", (cx, cy, zc), 700, (1.0, 0.85, 0.62), r=0.3)
    return o


# ------------------------------------------------------------------------------------------------------ stair cores
def _r3_flight(pr, mats, x, y0, y1, w, z0, z1, n):
    """A straight flight with closed risers along y (y0 -> y1, rising z0 -> z1): tread slabs, risers, two stringers, a round handrail + posts on the open side."""
    tr, rd, st, rail = mats
    dy = (y1 - y0) / n; dz = (z1 - z0) / n
    for i in range(n):
        yc = y0 + dy * (i + 0.5); zt = z0 + dz * (i + 1)
        pr[tr].append(("box", x, yc, zt - 0.02, w, abs(dy) + 0.03, 0.04))
        pr[rd].append(("box", x, y0 + dy * i + (0.01 if dy > 0 else -0.01), zt - dz / 2, w, 0.02, dz))
    for sx in (-1, 1):
        pr[st].append(("box", x + sx * (w / 2 - 0.02), (y0 + y1) / 2, (z0 + z1) / 2 - 0.1, 0.04, abs(y1 - y0) + 0.2, abs(z1 - z0) + 0.16))        # (a slab stringer, sloped by the treads on top)
    sgn = 1 if True else -1
    for sx in (-1, 1):
        xr = x + sx * (w / 2 + 0.03)
        pr[rail].append(("cyl", (xr, y0, z0 + 0.95), (xr, y1, z1 + 0.95), 0.025, 12))
        for i in range(0, n + 1, 3):
            yy = y0 + dy * i; zz = z0 + dz * i
            pr[rail].append(("cyl", (xr, yy, zz), (xr, yy, zz + 0.95), 0.012, 8))


def _r3_stairs(stats):
    """Plan zones utility_0/0 (5 x 8 m) and utility_0/1 (2 x 11 m) are the stair cores: a U-shaped dog-leg flight with a mid landing, and a straight flight (ref plan: stairs west and east)."""
    tr = _flat("ir_r3_tread", (0.62, 0.6, 0.57), 0.7); rd = _flat("ir_r3_riser", (0.74, 0.72, 0.68), 0.8); st = _flat("ir_r3_stringer", (0.1, 0.1, 0.11), 0.4, 0.8)
    rail = _plain_metal("ir_r3_rail", (0.7, 0.68, 0.64), 0.28)
    mats = (tr, rd, st, rail)
    n_ = 0
    lo, hi = _wall_face().inner_box("utility_0/0")
    if lo is not None:
        z0 = lo[2]; pr = {m: [] for m in mats}; H = 3.65 - z0
        xa, xb = lo[0] + 0.75, lo[0] + 2.25
        _r3_flight(pr, mats, xa, lo[1] + 0.8, lo[1] + 0.8 + 11 * 0.28, 1.15, z0, z0 + H / 2, 11)
        pr[tr].append(("box", (xa + xb) / 2, lo[1] + 0.8 + 11 * 0.28 + 0.6, z0 + H / 2 - 0.02, 3.1, 1.2, 0.04)); pr[st].append(("box", (xa + xb) / 2, lo[1] + 0.8 + 11 * 0.28 + 0.6, z0 + H / 2 - 0.12, 3.1, 1.2, 0.16))
        _r3_flight(pr, mats, xb + 0.05, lo[1] + 0.8 + 11 * 0.28, lo[1] + 0.8, 1.15, z0 + H / 2, z0 + H - 0.2, 11)
        _emit_mesh("H5R3Stairs0", pr); n_ += 1
    lo, hi = _wall_face().inner_box("utility_0/1")
    if lo is not None:
        z0 = lo[2]; pr = {m: [] for m in mats}; H = 3.65 - z0; xc = (lo[0] + hi[0]) / 2
        _r3_flight(pr, mats, xc, lo[1] + 1.0, lo[1] + 1.0 + 20 * 0.28, 1.15, z0, z0 + H - 0.2, 20)
        _emit_mesh("H5R3Stairs1", pr); n_ += 1
    for (cx_, cy_) in ((2.5, 3.5), (56.0, 3.0), (56.0, 8.0)):
        _light(f"ir_r3_stairlight_{int(cy_)}", "AREA", (cx_, cy_, 3.3), 260, (1.0, 0.85, 0.65), sx=1.2, sy=1.2)
    stats["r3_stairs"] = n_




def _wall_face():
    import wall_face
    return wall_face


def _ratio3(stats):
    """User 2026-10-26: Codex reference-match ratio >= 0.5 (refs_ratio.py): sea outside every window, guest suite 0/0 (lit media wall + TV, window lounge, pale rug, fan), sky lounge (grey seating, round rugs,
    window dining tables, palms, smooth columns), lift hall / corridor (veined floors, lit green recesses, tray / bay ceilings), banquet lobby / hall (sea windows, dark marble counter, gold coffers, crystal ball chandeliers,
    floral centrepieces), stair cores. Runs last; every part is isolated. ROOM_HOTEL5_SKIP=ratio3 turns it off."""
    for fn in (_r3_sea, _r3_suite, _r3_lounge, _r3_elev, _r3_corr, _r3_lobby, _r3_hall, _r3_stairs):
        try:
            bpy.context.view_layer.update(); fn(stats)
        except Exception as ex:                                  # noqa: BLE001 -- a part that fails must not sink the kit stage
            import traceback; traceback.print_exc()
            stats[f"h5_{fn.__name__}_error"] = repr(ex)[:160]


def _pkg_g_H5_fabric():
    """Gray woven upholstery using the local fabric PBR rather than flat boxes."""
    name='ir_pkg_g_H5_gray_weave'
    existing=bpy.data.materials.get(name)
    if existing is not None:
        return existing
    material=bpy.data.materials.new(name)
    material.use_nodes=True
    material['weathered']=True
    nodes,links=material.node_tree.nodes,material.node_tree.links
    shader=nodes['Principled BSDF']
    shader.inputs['Base Color'].default_value=(.28,.29,.30,1)
    shader.inputs['Roughness'].default_value=.82
    shader.inputs['Sheen Weight'].default_value=.25
    shader.inputs['Emission Strength'].default_value=0
    coordinates=nodes.new('ShaderNodeTexCoord')
    mapping=nodes.new('ShaderNodeVectorMath')
    mapping.operation='SCALE'
    mapping.inputs['Scale'].default_value=2
    links.new(coordinates.outputs['Object'],mapping.inputs[0])
    texture=nodes.new('ShaderNodeTexImage')
    texture.image=bpy.data.images.load('/bean/ir_pbr_assets/texturecan_environment_merged_v1/texturecan/texturecan_fabric_0022/base_color.jpg',check_existing=True)
    texture.projection='BOX'
    texture.projection_blend=.2
    links.new(mapping.outputs['Vector'],texture.inputs['Vector'])
    gray=nodes.new('ShaderNodeRGBToBW')
    links.new(texture.outputs['Color'],gray.inputs[0])
    variation=nodes.new('ShaderNodeMapRange')
    variation.inputs['To Min'].default_value=.92
    variation.inputs['To Max'].default_value=1.08
    links.new(gray.outputs[0],variation.inputs['Value'])
    tint=nodes.new('ShaderNodeMixRGB')
    tint.blend_type='MULTIPLY'
    tint.inputs[0].default_value=1
    tint.inputs[1].default_value=(.28,.29,.30,1)
    links.new(variation.outputs[0],tint.inputs[2])
    links.new(tint.outputs[0],shader.inputs['Base Color'])
    bump=nodes.new('ShaderNodeBump')
    bump.inputs['Distance'].default_value=.0003
    bump.inputs['Strength'].default_value=.25
    links.new(gray.outputs[0],bump.inputs['Height'])
    links.new(bump.outputs['Normal'],shader.inputs['Normal'])
    return material


def _pkg_g_H5_section(width,height,radius,steps=6):
    points=[]
    radius=min(radius,width/2-.0001,height/2-.0001)
    for x,y,start in [(width/2-radius,height/2-radius,0),(-width/2+radius,height/2-radius,90),(-width/2+radius,-height/2+radius,180),(width/2-radius,-height/2+radius,270)]:
        for i in range(steps+1):
            angle=math.radians(start+90*i/steps)
            points.append((x+radius*math.cos(angle),y+radius*math.sin(angle)))
    return points


def _pkg_g_H5_sweep(name,path,section,material):
    """Rounded furniture shell swept through (centre, horizontal normal) frames."""
    vertices=[]
    faces=[]
    count=len(section)
    for centre,normal in path:
        for horizontal,vertical in section:
            vertices.append((centre[0]+normal[0]*horizontal,centre[1]+normal[1]*horizontal,centre[2]+vertical))
    faces.append(tuple(reversed(range(count))))
    for row in range(len(path)-1):
        for i in range(count):
            j=(i+1)%count
            faces.append((row*count+i,row*count+j,(row+1)*count+j,(row+1)*count+i))
    faces.append(tuple((len(path)-1)*count+i for i in range(count)))
    mesh=bpy.data.meshes.new(name)
    mesh.from_pydata(vertices,[],faces)
    mesh.materials.append(material)
    mesh.update()
    import bmesh
    normals=bmesh.new()
    normals.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(normals,faces=list(normals.faces))
    normals.to_mesh(mesh)
    normals.free()
    obj=bpy.data.objects.new(name,mesh)
    bpy.context.scene.collection.objects.link(obj)
    for polygon in mesh.polygons:
        polygon.use_smooth=len(polygon.vertices)==4
    return obj


def _pkg_g_H5_sofa(name,x,y,z,yaw,material):
    radius=2.4
    angle=math.asin(1.30/radius)
    created=[]
    def path(a0,a1,depth,height,segments=72):
        result=[]
        for k in range(segments+1):
            theta=a0+(a1-a0)*k/segments
            normal=(math.cos(theta),-math.sin(theta))
            result.append(((radius*(1-math.cos(theta))+normal[0]*depth,radius*math.sin(theta)+normal[1]*depth,height),normal))
        return result
    created.append(_pkg_g_H5_sweep(name+'_base',path(-angle,angle,.27,.17),_pkg_g_H5_section(.70,.28,.09),material))
    created.append(_pkg_g_H5_sweep(name+'_back',path(-angle,angle,-.04,.55),_pkg_g_H5_section(.22,.60,.08),material))
    for k in range(3):
        a0=-angle+2*angle*k/3+.004
        a1=-angle+2*angle*(k+1)/3-.004
        created.append(_pkg_g_H5_sweep(name+'_seat'+str(k),path(a0,a1,.28,.365,28),_pkg_g_H5_section(.64,.14,.06),material))
        created.append(_pkg_g_H5_sweep(name+'_pad'+str(k),path(a0,a1,.085,.64,28),_pkg_g_H5_section(.13,.34,.055),material))
    for side in (-1,1):
        theta=side*angle
        base=(radius*(1-math.cos(theta)),radius*math.sin(theta))
        front=(math.cos(theta),-math.sin(theta))
        tangent=(math.sin(theta),math.cos(theta))
        arm=[((base[0]+front[0]*(.02+.58*k/24),base[1]+front[1]*(.02+.58*k/24),.53),tangent) for k in range(25)]
        created.append(_pkg_g_H5_sweep(name+'_arm'+str(side),arm,_pkg_g_H5_section(.16,.32,.075),material))
    points=[vertex.co for obj in created for vertex in obj.data.vertices]
    limits=[(min(p[i] for p in points),max(p[i] for p in points)) for i in range(3)]
    sizes=(1.0,2.8,.85)
    c,s=math.cos(yaw),math.sin(yaw)
    for obj in created:
        for vertex in obj.data.vertices:
            px=(vertex.co.x-sum(limits[0])/2)*sizes[0]/(limits[0][1]-limits[0][0])
            py=(vertex.co.y-sum(limits[1])/2)*sizes[1]/(limits[1][1]-limits[1][0])
            pz=(vertex.co.z-limits[2][0])*sizes[2]/(limits[2][1]-limits[2][0])
            vertex.co=(x+c*px-s*py,y+s*px+c*py,z+pz)
        obj.data.update()
        obj['pkg_g_H5_group']=name
        if '_arm' in obj.name:
            bevel=obj.modifiers.new('Rounded padded arm end','BEVEL')
            bevel.width=.03
            bevel.segments=3
    return created


def _pkg_g_H5_club(name,x,y,z,yaw,material):
    path=[]
    for i in range(81):
        angle=math.radians(65+230*i/80)
        path.append(((.35*math.cos(angle),.35*math.sin(angle),.52),(math.cos(angle),math.sin(angle))))
    created=[_pkg_g_H5_sweep(name+'_wrap',path,_pkg_g_H5_section(.16,.52,.075),material)]
    import bmesh
    bm=bmesh.new()
    for rx,ry,rz,height in [(.35,.35,.075,.35)]:
        result=bmesh.ops.create_uvsphere(bm,u_segments=64,v_segments=32,radius=1)
        for vertex in result['verts']:
            vertex.co=(vertex.co.x*rx,vertex.co.y*ry,vertex.co.z*rz+height)
    body=[]
    for height,radius in [(0,.28),(.02,.34),(.24,.35),(.31,.32)]:
        body.append([bm.verts.new((radius*math.cos(i*2*math.pi/64),radius*math.sin(i*2*math.pi/64),height)) for i in range(64)])
    bm.faces.new(tuple(reversed(body[0])))
    bm.faces.new(body[-1])
    for first,second in zip(body,body[1:]):
        for i in range(64):
            bm.faces.new((first[i],first[(i+1)%64],second[(i+1)%64],second[i]))
    mesh=bpy.data.meshes.new(name+'_seat')
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(material)
    obj=bpy.data.objects.new(name+'_seat',mesh)
    bpy.context.scene.collection.objects.link(obj)
    for polygon in mesh.polygons:
        polygon.use_smooth=True
    created.append(obj)
    c,s=math.cos(yaw),math.sin(yaw)
    for obj in created:
        for vertex in obj.data.vertices:
            px,py,pz=vertex.co
            vertex.co=(x+c*px-s*py,y+s*px+c*py,z+pz)
        obj.data.update()
        obj['pkg_g_H5_group']=name
        if '_arm' in obj.name:
            bevel=obj.modifiers.new('Rounded padded arm end','BEVEL')
            bevel.width=.03
            bevel.segments=3
    return created


def _pkg_g_H5_pedestal(name,x,y,z,material):
    import bmesh
    bm=bmesh.new()
    rings=[]
    for radius,height in [(.25,0),(.25,.025),(.235,.07),(.235,.37),(.26,.395),(.575,.395),(.575,.430)]:
        rings.append([bm.verts.new((x+radius*math.cos(i*2*math.pi/96),y+radius*math.sin(i*2*math.pi/96),z+height)) for i in range(96)])
    bm.faces.new(tuple(reversed(rings[0])))
    for a,b in zip(rings,rings[1:]):
        for i in range(96):
            face=bm.faces.new((a[i],a[(i+1)%96],b[(i+1)%96],b[i]))
            face.smooth=True
    bm.faces.new(rings[-1])
    mesh=bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(material)
    obj=bpy.data.objects.new(name,mesh)
    bpy.context.scene.collection.objects.link(obj)
    modifier=obj.modifiers.new('12mm tabletop edge','BEVEL')
    modifier.width=.012
    modifier.segments=3
    return obj


def _pkg_g_H5_lounge_seating(stats):
    """Proposal 1, explicitly prioritized by ORCH: one isolated seating swap."""
    scene=bpy.context.scene
    if scene.get('pkg_g_H5_lounge_seating'):
        return
    lo,hi=_room(LOUNGE)
    if lo is None:
        return
    old_sofas=[o for o in bpy.data.objects if o.type=='MESH' and not o.hide_render and _in_room(o,lo,hi) and o.name.startswith('Real_r3_lsofa')]
    old_chairs=[o for o in bpy.data.objects if o.type=='MESH' and not o.hide_render and _in_room(o,lo,hi) and o.name.startswith('Real_r3_club')]
    old_tables=[o for o in bpy.data.objects if o.type=='MESH' and not o.hide_render and _in_room(o,lo,hi) and o.name.startswith('Real_r3_ltable')]
    if (len(old_sofas),len(old_chairs),len(old_tables))!=(3,6,3):
        raise ValueError('Unexpected lounge furniture set; original objects retained')
    old_centres=[(2.6,11.9),(2.6,18.1),(8.2,15)]
    groups=[(2.6,11.9),(2.6,18.1),(7.6,15)]
    chair_centres=[[],[],[]]
    for obj in old_chairs:
        aa,bb=_bb(obj)
        x,y=(aa[0]+bb[0])/2,(aa[1]+bb[1])/2
        index=min(range(3),key=lambda i:math.hypot(x-old_centres[i][0],y-old_centres[i][1]))
        chair_centres[index].append((x,y))
    if any(len(row)!=2 for row in chair_centres):
        raise ValueError('Cannot identify two original chairs per seating island')
    chair_centres[2]=[(6.65,14.15),(6.65,15.85)]
    base=min(_bb(o)[0][2] for o in old_sofas)
    decor=[]
    for obj in bpy.data.objects:
        if obj.type=='MESH' and not obj.hide_render and _in_room(obj,lo,hi) and obj.name.startswith('Real_r3_ldecor'):
            aa,bb=_bb(obj)
            x,y=(aa[0]+bb[0])/2,(aa[1]+bb[1])/2
            index=min(range(3),key=lambda i:math.hypot(x-old_centres[i][0],y-old_centres[i][1]))
            decor.append((obj,index,aa,bb))
    fabric=_pkg_g_H5_fabric()
    dark=_wood('ir_pkg_g_H5_dark_oak',(.035,.028,.024))
    shader=dark.node_tree.nodes['Principled BSDF']
    for key,value in [('Roughness',.32),('Emission Strength',0)]:
        for link in list(shader.inputs[key].links):
            dark.node_tree.links.remove(link)
        shader.inputs[key].default_value=value
    for obj in old_sofas+old_chairs+old_tables:
        bpy.data.objects.remove(obj,do_unlink=True)
    for index,(gx,gy) in enumerate(groups):
        sx=1.25 if index<2 else 8.95
        yaw=0 if index<2 else math.pi
        _pkg_g_H5_sofa(f'PkgGH5Sofa({index})',sx,gy,base,yaw,fabric)
        for k,(x,y) in enumerate(chair_centres[index]):
            _pkg_g_H5_club(f'PkgGH5Club({index}|{k})',x,y,base,math.atan2(gy-y,gx-x),fabric)
        _pkg_g_H5_pedestal(f'PkgGH5Table({index})',gx,gy,base,dark)
    bpy.context.view_layer.update()
    moved=[]
    for index,(gx,gy) in enumerate(groups):
        placed=[]
        items=sorted([row for row in decor if row[1]==index],key=lambda row:row[2][2])
        for obj,_,aa,bb in items:
            dx,dy=gx-old_centres[index][0],gy-old_centres[index][1]
            target=base+.431
            is_book=bb[2]-aa[2]<.10 and (aa[1]+bb[1])/2>old_centres[index][1]
            if is_book:
                for previous in placed:
                    pa,pb=_bb(previous)
                    if aa[0]+dx<pb[0] and bb[0]+dx>pa[0] and aa[1]+dy<pb[1] and bb[1]+dy>pa[1]:
                        target=max(target,pb[2]+.001)
            obj.location+=Vector((dx,dy,target-aa[2]))
            bpy.context.view_layer.update()
            if is_book:
                placed.append(obj)
            moved.append({'object':obj.name,'group':index,'lowest_z':_bb(obj)[0][2],'support_z':target-.001})
    rug=bpy.data.objects.get('H5R3LoungeRugs')
    if rug is not None:
        rug.data=rug.data.copy()
        inverse=rug.matrix_world.inverted()
        for vertex in rug.data.vertices:
            point=rug.matrix_world@vertex.co
            if point.x>6:
                point.x=7.6+(point.x-8.5)*1.8/1.9
                point.y=15+(point.y-15)*1.8/1.9
                vertex.co=inverse@point
        rug.data.update()
    scene['pkg_g_H5_lounge_seating']=1
    stats['pkg_g_H5_lounge_seating']={'sofas':3,'club_chairs':6,'pedestal_tables':3,'decor':moved,'third_rug_centre':[7.6,15],'third_rug_radius':1.8}


def _pkg_g_H5_elevator_finish(stats):
    """Proposal 13: one bounded elevator-hall finish change; no lift layout edit."""
    scene=bpy.context.scene
    if scene.get('pkg_g_H5_elevator_finish'):
        return
    lo,hi=_room(ELEV)
    if lo is None:
        return
    material=bpy.data.materials.new('ir_pkg_g_H5_elevator_stone')
    material.use_nodes=True
    material['weathered']=True
    nodes,links=material.node_tree.nodes,material.node_tree.links
    shader=nodes['Principled BSDF']
    shader.inputs['Roughness'].default_value=.13
    shader.inputs['Emission Strength'].default_value=0
    geometry=nodes.new('ShaderNodeNewGeometry')
    plane=nodes.new('ShaderNodeVectorMath')
    plane.operation='MULTIPLY'
    plane.inputs[1].default_value=(1,1,0)
    links.new(geometry.outputs['Position'],plane.inputs[0])
    warp=nodes.new('ShaderNodeTexNoise')
    warp.inputs['Scale'].default_value=.25
    warp.inputs['Detail'].default_value=2
    links.new(plane.outputs[0],warp.inputs['Vector'])
    centred=nodes.new('ShaderNodeVectorMath')
    centred.operation='SUBTRACT'
    centred.inputs[1].default_value=(.5,.5,.5)
    links.new(warp.outputs['Color'],centred.inputs[0])
    strength=nodes.new('ShaderNodeVectorMath')
    strength.operation='SCALE'
    strength.inputs['Scale'].default_value=.4
    links.new(centred.outputs[0],strength.inputs[0])
    warped=nodes.new('ShaderNodeVectorMath')
    warped.operation='ADD'
    links.new(plane.outputs[0],warped.inputs[0])
    links.new(strength.outputs[0],warped.inputs[1])
    patches=nodes.new('ShaderNodeTexNoise')
    patches.inputs['Scale'].default_value=.7
    patches.inputs['Detail'].default_value=3
    patches.inputs['Roughness'].default_value=.65
    links.new(warped.outputs[0],patches.inputs['Vector'])
    ramp=nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.interpolation='EASE'
    ramp.color_ramp.elements[0].position=.43
    ramp.color_ramp.elements[0].color=(.16,.10,.09,1)
    ramp.color_ramp.elements[1].position=.46
    ramp.color_ramp.elements[1].color=(.70,.64,.54,1)
    links.new(patches.outputs['Fac'],ramp.inputs[0])
    fine=nodes.new('ShaderNodeTexNoise')
    fine.inputs['Scale'].default_value=12
    links.new(plane.outputs[0],fine.inputs['Vector'])
    modulation=nodes.new('ShaderNodeMapRange')
    modulation.inputs['To Min'].default_value=.95
    modulation.inputs['To Max'].default_value=1.05
    links.new(fine.outputs['Fac'],modulation.inputs['Value'])
    multiply=nodes.new('ShaderNodeMixRGB')
    multiply.blend_type='MULTIPLY'
    multiply.inputs[0].default_value=1
    links.new(ramp.outputs[0],multiply.inputs[1])
    links.new(modulation.outputs[0],multiply.inputs[2])
    links.new(multiply.outputs[0],shader.inputs['Base Color'])
    _set_floor(ELEV,material)
    oak=_wood('ir_pkg_g_H5_elevator_oak',(.40,.27,.14))
    textile=bpy.data.materials.new('ir_pkg_g_H5_elevator_textile')
    textile.use_nodes=True
    textile['weathered']=True
    ts=textile.node_tree.nodes['Principled BSDF']
    ts.inputs['Base Color'].default_value=(.32,.29,.25,1)
    ts.inputs['Roughness'].default_value=.9
    tc=textile.node_tree.nodes.new('ShaderNodeTexNoise')
    tc.inputs['Scale'].default_value=900
    bump=textile.node_tree.nodes.new('ShaderNodeBump')
    bump.inputs['Distance'].default_value=.0003
    bump.inputs['Strength'].default_value=.2
    textile.node_tree.links.new(tc.outputs['Fac'],bump.inputs['Height'])
    textile.node_tree.links.new(bump.outputs[0],ts.inputs['Normal'])
    bronze=_plain_metal('ir_pkg_g_H5_elevator_bronze',(.35,.22,.09),.25)
    light=bpy.data.materials.new('ir_pkg_g_H5_elevator_diffuser')
    light.use_nodes=True
    light['weathered']=True
    ls=light.node_tree.nodes['Principled BSDF']
    ls.inputs['Base Color'].default_value=(.8,.75,.65,1)
    ls.inputs['Emission Color'].default_value=(1,.80,.56,1)
    ls.inputs['Emission Strength'].default_value=2
    ls.inputs['Roughness'].default_value=.5
    old=bpy.data.objects.get('H5R3ElevStrips')
    if old is not None:
        bpy.data.objects.remove(old,do_unlink=True)
    bays=[]
    strips=[]
    for side,sign in [('W',1),('E',-1)]:
        face=_wall_face().face(ELEV,side)
        gaps=_door_gaps(1,face,lo[1],hi[1],pad=.18)
        gaps+=[(3.0,5.0)]
        if side=='E':
            gaps+=[(1.08,2.32),(5.68,6.92)]
        gaps=sorted(gaps)
        for begin,end in _segments(lo[1]+.15,hi[1]-.15,gaps,minw=.8):
            count=max(1,int((end-begin)/1.25))
            for index in range(count):
                a=begin+(end-begin)*index/count
                b=begin+(end-begin)*(index+1)/count
                centre=(a+b)/2
                width=b-a
                name=f'PkgGH5ElevBay({side}|{len(bays)})'
                groups=[(oak,[('box',face+sign*.0125,a+.065,1.7,.025,.13,3.0),('box',face+sign*.0125,b-.065,1.7,.025,.13,3.0)]),(textile,[('box',face+sign*.0125,centre,1.7,.025,width-.26,3.0)]),(bronze,[('box',face+sign*.027,a+.012,1.7,.008,.02,3.0),('box',face+sign*.027,b-.012,1.7,.008,.02,3.0)])]
                _fl().mesh_object(name,groups,bevel=False)
                obj=bpy.data.objects[name]
                md=obj.modifiers.new('3mm cladding edges','BEVEL')
                md.width=.003
                md.segments=3
                bays.append({'object':name,'side':side,'face':face,'span':[a,b],'door_gaps':gaps})
                for along in (a+.03,b-.03):
                    name=f'PkgGH5ElevStrip({side}|{len(strips)})'
                    _fl().mesh_object(name,[(light,[('box',face+sign*.04,along,1.7,.008,.015,3.0)])],bevel=False)
                    strips.append({'object':name,'side':side,'face':face,'front_offset':.044})
    if not bays:
        raise ValueError('No clear elevator wall bay available')
    scene['pkg_g_H5_elevator_finish']=1
    stats['pkg_g_H5_elevator_finish']={'bays':bays,'strips':strips,'floor_roughness':.13,'lift_layout_unchanged':True}


def _pkg_g_H5_sea_mapping(stats):
    """Proposal 4: continuous full-width sea cards with a shared horizon."""
    scene=bpy.context.scene
    if scene.get('pkg_g_H5_sea_mapping'):
        return
    materials={}
    for kind in ('sunset','day'):
        mat=bpy.data.materials.new('ir_pkg_g_H5_sea_'+kind)
        mat.use_nodes=True
        mat['weathered']=True
        nodes,links=mat.node_tree.nodes,mat.node_tree.links
        shader=nodes['Principled BSDF']
        shader.inputs['Roughness'].default_value=.5
        shader.inputs['Emission Strength'].default_value=.65
        uv=nodes.new('ShaderNodeUVMap')
        uv.uv_map='pkg_g_H5_horizon_uv'
        mapping=nodes.new('ShaderNodeMapping')
        mapping.inputs['Scale'].default_value=(1,1,1)
        mapping.inputs['Location'].default_value=(0,0,0)
        tex=nodes.new('ShaderNodeTexImage')
        tex.image=bpy.data.images.load(rc.sea_panorama(kind),check_existing=True)
        tex.extension='EXTEND'
        links.new(uv.outputs['UV'],mapping.inputs['Vector'])
        links.new(mapping.outputs['Vector'],tex.inputs['Vector'])
        links.new(tex.outputs['Color'],shader.inputs['Base Color'])
        links.new(tex.outputs['Color'],shader.inputs['Emission Color'])
        materials[kind]=mat
    targets=[]
    for obj in list(bpy.data.objects):
        if obj.type!='MESH':
            continue
        slots={i:('sunset' if slot.material.name=='ir_h5_sunset' else 'day') for i,slot in enumerate(obj.material_slots) if slot.material and (slot.material.name=='ir_h5_sunset' or slot.material.name.startswith('ir_bg_card_env'))}
        if slots:
            targets.append((obj,slots))
    if not targets:
        raise ValueError('No public sea or bedroom environment cards found')
    # Shared wall spans keep the panorama continuous if a wall has several panes.
    groups={}
    for obj,slots in targets:
        points=[obj.matrix_world@v.co for v in obj.data.vertices]
        extent=[max(p[i] for p in points)-min(p[i] for p in points) for i in (0,1)]
        axis=0 if extent[0]>=extent[1] else 1
        fixed=1-axis
        wall=round(sum(p[fixed] for p in points)/len(points),2)
        key=(tuple(sorted(set(slots.values()))),axis,wall)
        groups.setdefault(key,[]).append((obj,slots,points))
    records=[]
    for key,group in groups.items():
        axis=key[1]
        begin=min(p[axis] for _,_,points in group for p in points)
        end=max(p[axis] for _,_,points in group for p in points)
        if end-begin<.01:
            raise ValueError('Degenerate sea-card horizontal span')
        for obj,slots,points in group:
            obj.data=obj.data.copy()
            uv=obj.data.uv_layers.get('pkg_g_H5_horizon_uv') or obj.data.uv_layers.new(name='pkg_g_H5_horizon_uv')
            for poly in obj.data.polygons:
                if poly.material_index not in slots:
                    continue
                for li in poly.loop_indices:
                    p=points[obj.data.loops[li].vertex_index]
                    uv.data[li].uv=((p[axis]-begin)/(end-begin),.590+(p.z-1.50)*.17)
            for index,kind in slots.items():
                obj.data.materials[index]=materials[kind]
            obj.data.update()
            records.append({'object':obj.name,'axis':axis,'wall_span':[begin,end],'kinds':list(slots.values()),'horizon_z':1.5,'uv_horizon':.590})
    scene['pkg_g_H5_sea_mapping']=1
    stats['pkg_g_H5_sea_mapping']={'cards':records,'geometry_unchanged':True,'ordinary_materials_unchanged':True}


def _pkg_g_H5_banquet_carpet(stats):
    """Proposal 9: metric blue-gray/taupe carpet with narrow gold swirls."""
    scene=bpy.context.scene
    if scene.get('pkg_g_H5_banquet_carpet'):
        return
    mat=bpy.data.materials.new('ir_pkg_g_H5_banquet_carpet')
    mat.use_nodes=True
    mat['weathered']=True
    nodes,links=mat.node_tree.nodes,mat.node_tree.links
    shader=nodes['Principled BSDF']
    shader.inputs['Roughness'].default_value=.94
    shader.inputs['Metallic'].default_value=0
    shader.inputs['Emission Strength'].default_value=0
    geometry=nodes.new('ShaderNodeNewGeometry')
    xy=nodes.new('ShaderNodeVectorMath')
    xy.operation='MULTIPLY'
    xy.inputs[1].default_value=(.65,.65,0)
    links.new(geometry.outputs['Position'],xy.inputs[0])
    offset=nodes.new('ShaderNodeVectorMath')
    offset.operation='SUBTRACT'
    offset.inputs[1].default_value=(52*.65,16*.65,0)
    links.new(xy.outputs[0],offset.inputs[0])
    noise=nodes.new('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value=.7
    noise.inputs['Detail'].default_value=3
    noise.inputs['Roughness'].default_value=.65
    links.new(offset.outputs[0],noise.inputs['Vector'])
    centre=nodes.new('ShaderNodeVectorMath')
    centre.operation='SUBTRACT'
    centre.inputs[1].default_value=(.5,.5,.5)
    links.new(noise.outputs['Color'],centre.inputs[0])
    strength=nodes.new('ShaderNodeVectorMath')
    strength.operation='SCALE'
    strength.inputs['Scale'].default_value=2.0
    links.new(centre.outputs[0],strength.inputs[0])
    warped=nodes.new('ShaderNodeVectorMath')
    warped.operation='ADD'
    links.new(offset.outputs[0],warped.inputs[0])
    links.new(strength.outputs[0],warped.inputs[1])
    wave=nodes.new('ShaderNodeTexWave')
    wave.wave_type='RINGS'
    wave.rings_direction='SPHERICAL'
    wave.inputs['Scale'].default_value=1.0
    wave.inputs['Distortion'].default_value=12.0
    wave.inputs['Detail'].default_value=3
    wave.inputs['Detail Scale'].default_value=.7
    links.new(warped.outputs[0],wave.inputs['Vector'])
    base=nodes.new('ShaderNodeValToRGB')
    base.color_ramp.interpolation='EASE'
    colors=[(0,(.18,.23,.30,1)),(.35,(.18,.23,.30,1)),(.40,(.32,.28,.24,1)),(.62,(.32,.28,.24,1)),(.68,(.62,.58,.49,1)),(1,(.62,.58,.49,1))]
    base.color_ramp.elements.remove(base.color_ramp.elements[1])
    for index,(position,color) in enumerate(colors):
        element=base.color_ramp.elements[0] if index==0 else base.color_ramp.elements.new(position)
        element.position=position
        element.color=color
    links.new(wave.outputs['Fac'],base.inputs[0])
    gold=nodes.new('ShaderNodeValToRGB')
    gold.color_ramp.interpolation='CONSTANT'
    gold.color_ramp.elements[0].position=0
    gold.color_ramp.elements[0].color=(0,0,0,1)
    gold.color_ramp.elements[1].position=.47
    gold.color_ramp.elements[1].color=(1,1,1,1)
    for position,value in ((.49,0),(.64,1),(.66,0)):
        element=gold.color_ramp.elements.new(position)
        element.color=(value,value,value,1)
    links.new(wave.outputs['Fac'],gold.inputs[0])
    mix=nodes.new('ShaderNodeMixRGB')
    mix.inputs[2].default_value=(.52,.35,.12,1)
    links.new(gold.outputs[0],mix.inputs[0])
    links.new(base.outputs[0],mix.inputs[1])
    links.new(mix.outputs[0],shader.inputs['Base Color'])
    pile=nodes.new('ShaderNodeTexNoise')
    pile.inputs['Scale'].default_value=500
    links.new(geometry.outputs['Position'],pile.inputs['Vector'])
    bump=nodes.new('ShaderNodeBump')
    bump.inputs['Distance'].default_value=.0007
    bump.inputs['Strength'].default_value=.18
    links.new(pile.outputs['Fac'],bump.inputs['Height'])
    links.new(bump.outputs[0],shader.inputs['Normal'])
    _set_floor(HALL,mat)
    scene['pkg_g_H5_banquet_carpet']=1
    stats['pkg_g_H5_banquet_carpet']={'material':mat.name,'roughness':.94,'pile_distance_m':.0007,'gold_thresholds':[[.47,.49],[.64,.66]],'geometry_unchanged':True}


def _pkg_g_H5_corridor_carpet(stats):
    """Proposal 10: irregular cream/dark islands, world-metre carpet mapping."""
    scene=bpy.context.scene
    if scene.get('pkg_g_H5_corridor_carpet'):
        return
    mat=bpy.data.materials.new('ir_pkg_g_H5_corridor_carpet')
    mat.use_nodes=True
    mat['weathered']=True
    nodes,links=mat.node_tree.nodes,mat.node_tree.links
    shader=nodes['Principled BSDF']
    shader.inputs['Roughness'].default_value=.94
    shader.inputs['Metallic'].default_value=0
    shader.inputs['Emission Strength'].default_value=0
    geo=nodes.new('ShaderNodeNewGeometry')
    plane=nodes.new('ShaderNodeVectorMath')
    plane.operation='MULTIPLY'
    plane.inputs[1].default_value=(1,1,0)
    links.new(geo.outputs['Position'],plane.inputs[0])
    anchor=nodes.new('ShaderNodeVectorMath')
    anchor.operation='SUBTRACT'
    anchor.inputs[1].default_value=(10,8,0)
    links.new(plane.outputs[0],anchor.inputs[0])
    warp=nodes.new('ShaderNodeTexNoise')
    warp.inputs['Scale'].default_value=.22
    warp.inputs['Detail'].default_value=3
    links.new(anchor.outputs[0],warp.inputs['Vector'])
    centre=nodes.new('ShaderNodeVectorMath')
    centre.operation='SUBTRACT'
    centre.inputs[1].default_value=(.5,.5,.5)
    links.new(warp.outputs['Color'],centre.inputs[0])
    strength=nodes.new('ShaderNodeVectorMath')
    strength.operation='SCALE'
    strength.inputs['Scale'].default_value=.9
    links.new(centre.outputs[0],strength.inputs[0])
    warped=nodes.new('ShaderNodeVectorMath')
    warped.operation='ADD'
    links.new(anchor.outputs[0],warped.inputs[0])
    links.new(strength.outputs[0],warped.inputs[1])
    # A second noise warp gives 1.2 m distortion without a non-existent Noise socket.
    detail=nodes.new('ShaderNodeTexNoise')
    detail.inputs['Scale'].default_value=.55
    detail.inputs['Detail'].default_value=2
    links.new(warped.outputs[0],detail.inputs['Vector'])
    dc=nodes.new('ShaderNodeVectorMath')
    dc.operation='SUBTRACT'
    dc.inputs[1].default_value=(.5,.5,.5)
    links.new(detail.outputs['Color'],dc.inputs[0])
    ds=nodes.new('ShaderNodeVectorMath')
    ds.operation='SCALE'
    ds.inputs['Scale'].default_value=1.2
    links.new(dc.outputs[0],ds.inputs[0])
    final=nodes.new('ShaderNodeVectorMath')
    final.operation='ADD'
    links.new(warped.outputs[0],final.inputs[0])
    links.new(ds.outputs[0],final.inputs[1])
    patches=nodes.new('ShaderNodeTexNoise')
    patches.inputs['Scale'].default_value=.55
    patches.inputs['Detail'].default_value=3
    patches.inputs['Roughness'].default_value=.65
    links.new(final.outputs[0],patches.inputs['Vector'])
    def smooth_threshold(low,high):
        node=nodes.new('ShaderNodeMapRange')
        node.interpolation_type='SMOOTHSTEP'
        node.clamp=True
        node.inputs['From Min'].default_value=low
        node.inputs['From Max'].default_value=high
        links.new(patches.outputs['Fac'],node.inputs['Value'])
        return node.outputs[0]
    brown=nodes.new('ShaderNodeMixRGB')
    brown.inputs[1].default_value=(.13,.09,.075,1)
    brown.inputs[2].default_value=(.31,.24,.20,1)
    links.new(smooth_threshold(.3875,.4125),brown.inputs[0])
    cream=nodes.new('ShaderNodeMixRGB')
    cream.inputs[2].default_value=(.65,.58,.47,1)
    links.new(smooth_threshold(.5075,.5325),cream.inputs[0])
    links.new(brown.outputs[0],cream.inputs[1])
    links.new(cream.outputs[0],shader.inputs['Base Color'])
    pile=nodes.new('ShaderNodeTexNoise')
    pile.inputs['Scale'].default_value=500
    links.new(geo.outputs['Position'],pile.inputs['Vector'])
    bump=nodes.new('ShaderNodeBump')
    bump.inputs['Distance'].default_value=.0006
    bump.inputs['Strength'].default_value=.18
    links.new(pile.outputs['Fac'],bump.inputs['Height'])
    links.new(bump.outputs[0],shader.inputs['Normal'])
    _set_floor(CORR,mat)
    scene['pkg_g_H5_corridor_carpet']=1
    stats['pkg_g_H5_corridor_carpet']={'material':mat.name,'roughness':.94,'pile_distance_m':.0006,'anchor_m':[10,8],'transition_width':.025,'geometry_unchanged':True,'marble_edges_unchanged':True}


def _pkg_g_H5b_lobby_wall(stats):
    """R17 proposal 12: recessed bronze screens between tall stone/mirror bays."""
    scene=bpy.context.scene
    if scene.get('pkg_g_H5b_lobby_wall'):
        return
    lo,hi=_room(LOBBY)
    if lo is None:
        return
    face=_wall_face().face(LOBBY,'E')
    bronze=_plain_metal('ir_pkg_g_H5b_screen_bronze',(.38,.24,.10),.25)
    wood=_wood('ir_pkg_g_H5b_screen_walnut',(.20,.11,.055))
    stone=_veined('ir_pkg_g_H5b_screen_stone',(.68,.59,.45),(.35,.30,.24),1.2,0,.25,vein_scale=3)
    mirror=_plain_metal('ir_pkg_g_H5b_screen_mirror',(.86,.87,.88),.025)
    for mat in (bronze,wood,stone,mirror):
        mat.node_tree.nodes['Principled BSDF'].inputs['Emission Strength'].default_value=0
    glow=bpy.data.materials.new('ir_pkg_g_H5b_screen_edge')
    glow.use_nodes=True
    glow['weathered']=True
    shader=glow.node_tree.nodes['Principled BSDF']
    shader.inputs['Base Color'].default_value=(.8,.65,.42,1)
    shader.inputs['Emission Color'].default_value=(1,.74,.40,1)
    shader.inputs['Emission Strength'].default_value=3
    start,end=lo[1]+1.1,hi[1]-1.1
    gaps=_door_gaps(1,face,start,end,pad=.12)
    bays=[]
    for begin,finish in _segments(start,end,gaps,minw=.7):
        count=max(1,round((finish-begin)/1.06))
        for i in range(count):
            a=begin+(finish-begin)*i/count
            b=begin+(finish-begin)*(i+1)/count
            width=b-a
            centre=(a+b)/2
            kind=('mirror','stone','screen','screen','screen','stone','mirror','screen')[len(bays)%8]
            groups={bronze:[],wood:[],stone:[],mirror:[],glow:[]}
            groups[wood].append(('box',face-.023,centre,1.80,.025,width-.025,3.30))
            for y in (a+.04,b-.04):
                groups[stone].append(('box',face-.060,y,1.80,.09,.08,3.30))
                groups[bronze].append(('box',face-.110,y,1.80,.10,.026,3.30))
                groups[glow].append(('box',face-.082,y+.026,1.80,.006,.008,3.15))
            for z in (.19,3.41):
                groups[bronze].append(('box',face-.110,centre,z,.10,width-.025,.035))
            if kind=='screen':
                n=max(2,round((width-.16)/.16))
                for j in range(n+1):
                    y=a+.10+(width-.20)*j/n
                    groups[bronze].append(('box',face-.100,y,1.80,.065,.018,3.17))
                for j in range(15):
                    z=.27+j*.218
                    groups[bronze].append(('box',face-.126,centre,z,.035,width-.18,.018))
            else:
                groups[mirror if kind=='mirror' else stone].append(('box',face-.057,centre,1.80,.035,width-.18,3.16))
                for z in (1.16,2.37):
                    groups[bronze].append(('box',face-.080,centre,z,.025,width-.18,.018))
            name=f'PkgGH5bLobbyBay({len(bays)}|{kind})'
            _fl().mesh_object(name,[(m,p) for m,p in groups.items() if p],bevel=False)
            obj=bpy.data.objects[name]
            bevel=obj.modifiers.new('3mm metal and stone edges','BEVEL')
            bevel.width=.003
            bevel.segments=3
            bays.append({'object':name,'kind':kind,'span':[a,b],'inner_face_x':face,'front_x':face-.16,'door_gaps':gaps})
    if not bays:
        raise ValueError('No safe lobby screen spans')
    for name in ('H5LatticeBack','H5LatticeBars'):
        obj=bpy.data.objects.get(name)
        if obj is not None:
            bpy.data.objects.remove(obj,do_unlink=True)
    scene['pkg_g_H5b_lobby_wall']=1
    stats['pkg_g_H5b_lobby_wall']={'bays':bays,'replaced':['H5LatticeBack','H5LatticeBars'],'whole_backing_emission':0,'depth_m':.16}


def _pkg_g_H5b_inlay(stats):
    """R17 proposal 11: expose the existing border without moving the floor."""
    scene=bpy.context.scene
    if scene.get('pkg_g_H5b_inlay'):
        return
    obj=bpy.data.objects.get('H5LobbyInlay')
    floor=bpy.data.objects.get(LOBBY+'.floor')
    if obj is None or floor is None:
        raise ValueError('Lobby border or floor missing')
    before=_bb(obj)
    floor_z=_bb(floor)[1][2]
    delta=floor_z+.00325-before[1][2]
    obj.location.z+=delta
    bpy.context.view_layer.update()
    obj.data=obj.data.copy()
    component_tops=[]
    for index,material in enumerate(obj.data.materials):
        indices={vi for face in obj.data.polygons if face.material_index==index for vi in face.vertices}
        if not indices:
            continue
        top=max((obj.matrix_world@obj.data.vertices[vi].co).z for vi in indices)
        dz=floor_z+.00325-top
        local_delta=obj.matrix_world.to_3x3().inverted()@Vector((0,0,dz))
        for vi in indices:
            obj.data.vertices[vi].co+=local_delta
        component_tops.append({'material':material.name,'additional_vertex_lift_m':dz,'new_top_m':floor_z+.00325})
    obj.data.update()
    bpy.context.view_layer.update()
    after=_bb(obj)
    if abs(delta)>.015:
        raise ValueError('Unexpected inlay height change')
    scene['pkg_g_H5b_inlay']=1
    stats['pkg_g_H5b_inlay']={'object':obj.name,'delta_z_m':delta,'clearance_m':after[1][2]-floor_z,'xy_unchanged':True,'before':before,'after':after,'material_components':component_tops}


def _pkg_g_H5b_columns(stats):
    """R17 proposal 8: smooth shafts, split cap normals, original centres."""
    scene=bpy.context.scene
    if scene.get('pkg_g_H5b_columns'):
        return
    old=bpy.data.objects.get('H5LoungeColumns')
    if old is None:
        raise ValueError('Original lounge column mesh missing')
    points=[old.matrix_world@v.co for v in old.data.vertices]
    seeds=[(3.74778,9.83934),(6.43425,15.0),(3.74778,20.16066)]
    groups=[[] for _ in seeds]
    for p in points:
        index=min(range(3),key=lambda i:(p.x-seeds[i][0])**2+(p.y-seeds[i][1])**2)
        groups[index].append(p)
    measured=[]
    for group in groups:
        if not group:
            raise ValueError('Column grouping failed')
        centre=[(min(p[i] for p in group)+max(p[i] for p in group))/2 for i in (0,1)]
        measured.append((centre[0],centre[1],min(p.z for p in group),max(p.z for p in group)))
    mat=bpy.data.materials.new('ir_pkg_g_H5b_champagne')
    mat.use_nodes=True
    mat['weathered']=True
    shader=mat.node_tree.nodes['Principled BSDF']
    shader.inputs['Base Color'].default_value=(.62,.50,.37,1)
    shader.inputs['Metallic'].default_value=.8
    shader.inputs['Roughness'].default_value=.27
    anisotropy=shader.inputs.get('Anisotropic') or shader.inputs.get('Anisotropic IOR Level')
    if anisotropy is None:
        raise ValueError('Missing anisotropy socket: '+str([s.name for s in shader.inputs]))
    anisotropy.default_value=.25
    shader.inputs['Emission Strength'].default_value=0
    records=[]
    for index,(x,y,z0,z1) in enumerate(measured):
        verts=[]
        for z in (z0,z1):
            verts.extend((x+.30*math.cos(2*math.pi*j/128),y+.30*math.sin(2*math.pi*j/128),z) for j in range(128))
        faces=[tuple(reversed(range(128))),tuple(range(128,256))]
        faces.extend((j,(j+1)%128,(j+1)%128+128,j+128) for j in range(128))
        mesh=bpy.data.meshes.new('PkgGH5bColumnMesh'+str(index))
        mesh.from_pydata(verts,[],faces)
        mesh.materials.append(mat)
        mesh.update()
        for face in mesh.polygons:
            face.use_smooth=len(face.vertices)==4
        obj=bpy.data.objects.new('PkgGH5bColumn('+str(index)+')',mesh)
        scene.collection.objects.link(obj)
        bevel=obj.modifiers.new('8mm rounded rims','BEVEL')
        bevel.width=.008
        bevel.segments=3
        bevel.limit_method='ANGLE'
        normal=obj.modifiers.new('Flat caps and cylindrical side normals','WEIGHTED_NORMAL')
        normal.keep_sharp=True
        records.append({'object':obj.name,'centre':[x,y],'base_z':z0,'top_z':z1,'radius_m':.30})
    bpy.data.objects.remove(old,do_unlink=True)
    scene['pkg_g_H5b_columns']=1
    stats['pkg_g_H5b_columns']={'columns':records,'shaft_sides':128,'replaced':['H5LoungeColumns'],'slab_and_rail_unchanged':True}


def _pkg_g_H5b_palms(stats):
    """R17 proposal 7: dense pinnate foliage, retained square planters."""
    scene=bpy.context.scene
    if scene.get('pkg_g_H5b_palms'):
        return
    lo,hi=_room(LOUNGE)
    old=[bpy.data.objects.get('Real_r3_palm'+suffix) for suffix in ('','.001','.002')]
    if any(obj is None or not _in_room(obj,lo,hi) for obj in old):
        raise ValueError('Cannot isolate the three lounge palms')
    materials=[]
    for index,rgb in enumerate(((.025,.13,.035),(.055,.20,.04),(.10,.28,.05))):
        mat=bpy.data.materials.new('ir_pkg_g_H5b_palm_green'+str(index))
        mat.use_nodes=True
        mat['weathered']=True
        shader=mat.node_tree.nodes['Principled BSDF']
        shader.inputs['Base Color'].default_value=(*rgb,1)
        shader.inputs['Roughness'].default_value=.50
        shader.inputs['Sheen Weight'].default_value=.15
        shader.inputs['Subsurface Weight'].default_value=.03
        shader.inputs['Emission Strength'].default_value=0
        materials.append(mat)
    stem=_flat('ir_pkg_g_H5b_palm_stem',(.12,.14,.035),.62)
    rows=[]
    for index,(cx,cy) in enumerate(((.9,15),(4.9,21.1),(9.3,11.5))):
        rg=random.Random(7550+index)
        verts=[]
        faces=[]
        slots=[]
        ribs=[]
        safe_radius=min(.65,cx-lo[0]-.06,hi[0]-cx-.06,cy-lo[1]-.06,hi[1]-cy-.06)
        base=lo[2]+.55
        leaflets=0
        for trunk,height in enumerate((1.35,1.60,1.78)):
            tx,ty=cx+.055*math.cos(trunk*2.1),cy+.055*math.sin(trunk*2.1)
            root=Vector((tx,ty,base+height))
            ribs.append(('cyl',(tx,ty,base),tuple(root),.013,8))
            for frond in range(10):
                angle=frond*2*math.pi/10+trunk*.65+rg.uniform(-.15,.15)
                outward=Vector((math.cos(angle),math.sin(angle),0))
                sideways=Vector((-math.sin(angle),math.cos(angle),0))
                reach=rg.uniform(.40,.55)
                lift=rg.uniform(.30,.48)
                def point(t):
                    return root+outward*(reach*t)+Vector((0,0,lift*math.sin(math.pi*.85*t)-.08*t))
                for j in range(12):
                    ribs.append(('cyl',tuple(point(j/12)),tuple(point((j+1)/12)),.0022,5))
                for j in range(25):
                    t=.07+.90*j/24
                    start=point(t)
                    length=(.045+.15*math.sin(math.pi*t)**.65)*rg.uniform(.85,1.12)
                    for side in (-1,1):
                        begin=len(verts)
                        for k in range(9):
                            q=k/8
                            centre=start+sideways*(side*length*q)+outward*(.08*q*q)+Vector((0,0,.025*math.sin(math.pi*q)-.06*q*q))
                            width=.012*math.sin(math.pi*q)**.7+.0003
                            for lane in (-1,0,1):
                                p=centre+outward*(lane*width)+Vector((0,0,.004*(1-abs(lane))*math.sin(math.pi*q)))
                                verts.append(tuple(p))
                        for k in range(8):
                            for lane in (0,1):
                                a=begin+k*3+lane
                                faces.append((a,a+1,a+4,a+3))
                                slots.append(rg.randrange(3))
                        leaflets+=1
        radius=max(math.hypot(v[0]-cx,v[1]-cy) for v in verts)
        scale=min(1,safe_radius/radius)
        verts=[(cx+(x-cx)*scale,cy+(y-cy)*scale,z) for x,y,z in verts]
        mesh=bpy.data.meshes.new('PkgGH5bPalmLeaves'+str(index))
        mesh.from_pydata(verts,[],faces)
        for material in materials:
            mesh.materials.append(material)
        for poly,slot in zip(mesh.polygons,slots):
            poly.material_index=slot
            poly.use_smooth=True
        mesh.update()
        obj=bpy.data.objects.new('PkgGH5bPalm('+str(index)+')',mesh)
        scene.collection.objects.link(obj)
        adjusted=[]
        for _,a,b,radius,segments in ribs:
            a=(cx+(a[0]-cx)*scale,cy+(a[1]-cy)*scale,a[2])
            b=(cx+(b[0]-cx)*scale,cy+(b[1]-cy)*scale,b[2])
            adjusted.append(('cyl',a,b,radius,segments))
        _fl().mesh_object('PkgGH5bPalmStems('+str(index)+')',[(stem,adjusted)],bevel=False)
        rows.append({'object':obj.name,'centre':[cx,cy],'soil_z':base,'fronds':30,'leaflets':leaflets,'radius_m':safe_radius,'xy_scale':scale})
    removed=[obj.name for obj in old]
    for obj in old:
        bpy.data.objects.remove(obj,do_unlink=True)
    scene['pkg_g_H5b_palms']=1
    stats['pkg_g_H5b_palms']={'plants':rows,'replaced':removed,'planters_unchanged':True,'hall_palms_unchanged':True}


def _pkg_g_H5b_lobby_coffers(stats):
    """R17 proposal 13: deep timber/gold coffers; retain lower wall sconces."""
    import bmesh
    scene=bpy.context.scene
    if scene.get('pkg_g_H5b_lobby_coffers'):
        return
    lo,hi=_room(LOBBY)
    old=bpy.data.objects.get('H5R3LobbyCoffer')
    if old is None:
        raise ValueError('Original coffer/sconce mesh missing')
    lower_before=sorted(tuple(round(v,6) for v in old.matrix_world@p.co) for p in old.data.vertices if (old.matrix_world@p.co).z<3.1)
    mesh=old.data.copy()
    bm=bmesh.new()
    bm.from_mesh(mesh)
    remove=[v for v in bm.verts if (old.matrix_world@v.co).z>=3.1]
    bmesh.ops.delete(bm,geom=remove,context='VERTS')
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    old.data=mesh
    lower_after=sorted(tuple(round(v,6) for v in old.matrix_world@p.co) for p in old.data.vertices)
    if lower_before!=lower_after:
        raise ValueError('Lower wall sconces changed')
    wood=_wood('ir_pkg_g_H5b_coffer_walnut',(.25,.15,.07))
    bronze=_plain_metal('ir_pkg_g_H5b_coffer_bronze',(.50,.33,.13),.25)
    cream=_flat('ir_pkg_g_H5b_coffer_cream',(.82,.78,.69),.65)
    light=_emit('ir_pkg_g_H5b_coffer_strip',(1,.74,.40),3)
    for material in (wood,bronze,cream):
        material.node_tree.nodes['Principled BSDF'].inputs['Emission Strength'].default_value=0
    groups={wood:[],bronze:[],cream:[],light:[]}
    x0,x1=lo[0]+.12,hi[0]-.12
    y0,y1=lo[1]+.12,hi[1]-.12
    xs=[x0+(x1-x0)*j/3 for j in range(4)]
    ys=[y0+(y1-y0)*j/3 for j in range(4)]
    for x in xs:
        groups[wood].append(('box',x,(y0+y1)/2,3.50,.22,y1-y0+.22,.30))
        for side in (-1,1):
            groups[bronze].append(('box',x+side*.112,(y0+y1)/2,3.48,.014,y1-y0,.22))
    for y in ys:
        for begin,end in zip(xs,xs[1:]):
            centre=(begin+end)/2
            groups[wood].append(('box',centre,y,3.50,end-begin-.22,.22,.30))
            for side in (-1,1):
                groups[bronze].append(('box',centre,y+side*.112,3.48,end-begin-.26,.014,.22))
    lights=[]
    for i in range(3):
        for j in range(3):
            cx,cy=(xs[i]+xs[i+1])/2,(ys[j]+ys[j+1])/2
            width,depth=xs[i+1]-xs[i]-.25,ys[j+1]-ys[j]-.25
            groups[cream].append(('box',cx,cy,3.615,width,depth,.025))
            for x in (xs[i]+.135,xs[i+1]-.135):
                groups[light].append(('box',x,cy,3.57,.008,depth,.008))
            for y in (ys[j]+.135,ys[j+1]-.135):
                groups[light].append(('box',cx,y,3.57,width,.008,.008))
            lamp=_light(f'ir_pkg_g_H5b_coffer_{i}_{j}','AREA',(cx,cy,3.44),90,(1,.83,.62),sx=1.5,sy=1.5)
            lights.append(lamp.name)
    _fl().mesh_object('PkgGH5bLobbyCoffers',[(m,p) for m,p in groups.items()],bevel=False)
    obj=bpy.data.objects['PkgGH5bLobbyCoffers']
    bevel=obj.modifiers.new('5mm beam edges','BEVEL')
    bevel.width=.005
    bevel.segments=3
    scene['pkg_g_H5b_lobby_coffers']=1
    stats['pkg_g_H5b_lobby_coffers']={'modified':['H5R3LobbyCoffer'],'lower_sconce_vertices_preserved':len(lower_after),'beam_bottom_m':3.35,'beam_depth_m':.30,'bays':9,'new_lights':lights,'pendants_unchanged':True}


def _pkg_g_H5b_hall_bays(stats):
    """R17 proposal 1: measured marble/timber/gold bays and proper wall lamps."""
    import bmesh
    scene=bpy.context.scene
    if scene.get('pkg_g_H5b_hall_bays'):
        return
    lo,hi=_room(HALL)
    face=_wall_face().face(HALL,'E')
    old=bpy.data.objects.get('H5R3HallDecor')
    if old is None:
        raise ValueError('Joined hall decor missing')
    retained={p.material_index for p in old.data.polygons if old.data.materials[p.material_index].name=='ir_r3_planter'}
    if not retained:
        raise ValueError('Cannot identify planter faces')
    keep_indices={i for p in old.data.polygons if p.material_index in retained for i in p.vertices}
    keep_before=sorted(tuple(round(v,6) for v in old.matrix_world@old.data.vertices[i].co) for i in keep_indices)
    wood=_wood('ir_pkg_g_H5b_hall_walnut',(.22,.13,.065))
    stone=_veined('ir_pkg_g_H5b_hall_marble',(.70,.62,.48),(.34,.30,.24),1.4,0,.25,vein_scale=4)
    brass=_plain_metal('ir_pkg_g_H5b_hall_brass',(.65,.44,.17),.23)
    shade=bpy.data.materials.new('ir_pkg_g_H5b_hall_lamp_shade')
    shade.use_nodes=True
    shade['weathered']=True
    shader=shade.node_tree.nodes['Principled BSDF']
    shader.inputs['Base Color'].default_value=(.85,.75,.56,1)
    shader.inputs['Emission Color'].default_value=(1,.80,.51,1)
    shader.inputs['Emission Strength'].default_value=3
    rows=[]
    gaps=_door_gaps(1,face,lo[1],hi[1],pad=.12)
    for y in (12.8,14.2,18.2,19.8):
        a,b=y-.45,y+.45
        if any(a<gb and b>ga for ga,gb in gaps):
            continue
        groups={wood:[],stone:[],brass:[],shade:[]}
        groups[wood].append(('box',face-.025,y,1.70625,.035,.90,3.15))
        groups[stone].append(('box',face-.048,y,1.70625,.025,.74,3.00))
        for yy in (a+.035,b-.035):
            groups[brass].append(('box',face-.064,yy,1.70625,.045,.025,3.15))
        for z in (.145,3.2675):
            groups[brass].append(('box',face-.064,y,z,.045,.90,.025))
        for z in (1.12,2.40):
            groups[brass].append(('box',face-.068,y,z,.018,.75,.016))
        rc.sconce(groups,brass,shade,face-.075,y,1.98,-1,0,'ir_pkg_g_H5b_hall_sconce_'+str(len(rows)))
        name='PkgGH5bHallBay('+str(len(rows))+')'
        _fl().mesh_object(name,[(m,p) for m,p in groups.items() if p],bevel=False)
        obj=bpy.data.objects[name]
        bevel=obj.modifiers.new('3mm frame moulding','BEVEL')
        bevel.width=.003
        bevel.segments=3
        rows.append({'object':name,'span':[a,b],'door_gaps':gaps,'inner_face_x':face,'sconce_z':1.98})
    if not rows:
        raise ValueError('All hall wall bays obstruct doors')
    mesh=old.data.copy()
    bm=bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.delete(bm,geom=[f for f in bm.faces if f.material_index not in retained],context='FACES_ONLY')
    bmesh.ops.delete(bm,geom=[v for v in bm.verts if not v.link_faces],context='VERTS')
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    old.data=mesh
    keep_after=sorted(tuple(round(v,6) for v in old.matrix_world@p.co) for p in old.data.vertices)
    if keep_before!=keep_after:
        raise ValueError('Hall planter geometry changed')
    for name in ('ir_r3_hsc_0','ir_r3_hsc_1'):
        light=bpy.data.objects.get(name)
        if light is not None and light.type=='LIGHT':
            bpy.data.objects.remove(light,do_unlink=True)
    scene['pkg_g_H5b_hall_bays']=1
    stats['pkg_g_H5b_hall_bays']={'modified':['H5R3HallDecor'],'bays':rows,'planter_vertices_preserved':len(keep_after),'old_planters_retained':True}


def _pkg_g_H5b_bouquets(stats):
    """R17 proposal 5: low white rosettes, bent leaves and clear glass vases."""
    scene=bpy.context.scene
    if scene.get('pkg_g_H5b_bouquets'):
        return
    lo,hi=_room(HALL)
    tables=[o for o in bpy.data.objects if o.type=='MESH' and o.name.startswith('H5Tablecloth') and _in_room(o,lo,hi)]
    old=[o for o in bpy.data.objects if o.type=='MESH' and o.name.startswith('Real_r3_flowers') and _in_room(o,lo,hi)]
    if len(tables)!=12 or len(old)!=12:
        raise ValueError(f'Expected twelve hall tables/flowers, found {len(tables)}/{len(old)}')
    petal=bpy.data.materials.new('ir_pkg_g_H5b_white_petals')
    petal.use_nodes=True
    petal['weathered']=True
    bs=petal.node_tree.nodes['Principled BSDF']
    bs.inputs['Base Color'].default_value=(.85,.83,.77,1)
    bs.inputs['Roughness'].default_value=.55
    bs.inputs['Subsurface Weight'].default_value=.08
    leaf=_flat('ir_pkg_g_H5b_bouquet_leaf',(.045,.16,.035),.50)
    stem=_flat('ir_pkg_g_H5b_bouquet_stem',(.08,.16,.035),.55)
    glass=bpy.data.materials.new('ir_pkg_g_H5b_bouquet_glass')
    glass.use_nodes=True
    glass['weathered']=True
    gs=glass.node_tree.nodes['Principled BSDF']
    gs.inputs['Base Color'].default_value=(.94,.98,.96,1)
    gs.inputs['Transmission Weight'].default_value=1
    gs.inputs['IOR'].default_value=1.45
    gs.inputs['Roughness'].default_value=.07
    rows=[]
    for index,table in enumerate(sorted(tables,key=lambda o:o.name)):
        low,high=_bb(table)
        cx,cy=(low[0]+high[0])/2,(low[1]+high[1])/2
        base=high[2]+.001
        rg=random.Random(9410+index)
        verts=[]
        faces=[]
        slots=[]
        stems=[]
        phase=rg.random()*2*math.pi
        for k in range(52):
            t=(k+.5)/52
            radius=.215*math.sqrt(1-t*t)
            angle=k*2.399963+phase
            pos=Vector((cx+radius*math.cos(angle),cy+radius*math.sin(angle),base+.16+.18*t))
            normal=Vector((pos.x-cx,pos.y-cy,.30)).normalized()
            rotation=normal.to_track_quat('Z','Y')
            size=rg.uniform(.034,.046)
            for ring,count,factor in ((0,6,1),(1,4,.61)):
                for j in range(count):
                    az=j*2*math.pi/count+phase+ring*.45+rg.uniform(-.12,.12)
                    along=Vector((math.cos(az),math.sin(az),0))
                    across=Vector((-math.sin(az),math.cos(az),0))
                    first=len(verts)
                    for q in range(6):
                        u=q/5
                        width=size*.45*math.sin(math.pi*u)**.65+.0002
                        for side in (-1,0,1):
                            local=along*(size*factor*u)+across*(side*width*factor)+Vector((0,0,.016*ring+.012*math.sin(math.pi*u)-.007*u*u+.003*abs(side)*math.sin(math.pi*u)))
                            verts.append(tuple(pos+rotation@local))
                    for q in range(5):
                        for side in (0,1):
                            a=first+q*3+side
                            faces.append((a,a+3,a+4,a+1))
                            slots.append(0)
            stems.append(('cyl',(cx+rg.uniform(-.025,.025),cy+rg.uniform(-.025,.025),base+.015),tuple(pos),.0015,5))
        for j in range(18):
            angle=j*2*math.pi/18+phase
            outward=Vector((math.cos(angle),math.sin(angle),0))
            sideways=Vector((-math.sin(angle),math.cos(angle),0))
            first=len(verts)
            for q in range(9):
                u=q/8
                centre=Vector((cx,cy,base+.13))+outward*(.12+.15*u)+Vector((0,0,.035*math.sin(math.pi*u)-.025*u))
                for side in (-1,0,1):
                    pos=centre+sideways*(side*.028*math.sin(math.pi*u))
                    pos.z+=.005*(1-abs(side))*math.sin(math.pi*u)
                    verts.append(tuple(pos))
            for q in range(8):
                for side in (0,1):
                    a=first+q*3+side
                    faces.append((a,a+3,a+4,a+1))
                    slots.append(1)
        mesh=bpy.data.meshes.new('PkgGH5bBouquetMesh'+str(index))
        mesh.from_pydata(verts,[],faces)
        mesh.materials.append(petal)
        mesh.materials.append(leaf)
        for face,slot in zip(mesh.polygons,slots):
            face.material_index=slot
            face.use_smooth=True
        mesh.update()
        obj=bpy.data.objects.new('PkgGH5bBouquet('+str(index)+')',mesh)
        scene.collection.objects.link(obj)
        _fl().mesh_object('PkgGH5bBouquetStems('+str(index)+')',[(stem,stems)],bevel=False)
        vase_verts=[]
        for z,radius in ((0,.060),(.012,.073),(.085,.073),(.125,.062),(.130,.065)):
            vase_verts.extend((cx+radius*math.cos(j*2*math.pi/48),cy+radius*math.sin(j*2*math.pi/48),base+z) for j in range(48))
        vase_faces=[tuple(reversed(range(48)))]
        vase_faces.extend((k*48+j,k*48+(j+1)%48,(k+1)*48+(j+1)%48,(k+1)*48+j) for k in range(4) for j in range(48))
        vm=bpy.data.meshes.new('PkgGH5bVaseMesh'+str(index))
        vm.from_pydata(vase_verts,[],vase_faces)
        vm.materials.append(glass)
        for face in vm.polygons:
            face.use_smooth=len(face.vertices)==4
        vm.update()
        vase=bpy.data.objects.new('PkgGH5bVase('+str(index)+')',vm)
        scene.collection.objects.link(vase)
        solid=vase.modifiers.new('2mm glass wall','SOLIDIFY')
        solid.thickness=.002
        solid.offset=1
        rows.append({'table':table.name,'object':obj.name,'blooms':52,'table_top_z':high[2],'vase_base_z':base,'contact_gap_m':.001,'max_radius_m':.275,'top_z':max(v[2] for v in verts)})
    removed=[obj.name for obj in old]
    for obj in old:
        bpy.data.objects.remove(obj,do_unlink=True)
    scene['pkg_g_H5b_bouquets']=1
    stats['pkg_g_H5b_bouquets']={'arrangements':rows,'replaced':removed,'all_table_heights_unchanged':True}


def _pkg_g_H5b_seating_finish(stats):
    """R17 proposal 10: continuous curved backs, softer seats and woven gray."""
    import bmesh
    scene=bpy.context.scene
    if scene.get('pkg_g_H5b_seating_finish'):
        return
    original=bpy.data.materials.get('ir_pkg_g_H5_gray_weave')
    if original is None:
        raise ValueError('Curved lounge upholstery material missing')
    pads=[o for o in bpy.data.objects if o.name.startswith('PkgGH5Sofa(') and '_pad' in o.name]
    backs=[o for o in bpy.data.objects if o.name.startswith('PkgGH5Sofa(') and o.name.endswith('_back')]
    if len(pads)!=9 or len(backs)!=3:
        raise ValueError('Cannot isolate curved back cushions')
    material=original.copy()
    material.name='ir_pkg_g_H5b_neutral_gray_weave'
    nodes=material.node_tree.nodes
    shader=nodes['Principled BSDF']
    shader.inputs['Base Color'].default_value=(.24,.24,.23,1)
    shader.inputs['Roughness'].default_value=.86
    shader.inputs['Sheen Weight'].default_value=.25
    shader.inputs['Emission Strength'].default_value=0
    for node in nodes:
        if node.type=='MIX_RGB' and node.blend_type=='MULTIPLY':
            node.inputs[1].default_value=(.24,.24,.23,1)
        if node.type=='MAP_RANGE':
            node.inputs['To Min'].default_value=.88
            node.inputs['To Max'].default_value=1.12
    plinth=_flat('ir_pkg_g_H5b_upholstery_plinth',(.025,.022,.018),.45)
    modified=[]
    recolored=[]
    lo,hi=_room(LOUNGE)
    cut_z=lo[2]+.12
    for obj in list(bpy.data.objects):
        if obj.type!='MESH' or not obj.name.startswith(('PkgGH5Sofa(','PkgGH5Club(')) or obj in pads:
            continue
        obj.data=obj.data.copy()
        for index,mat in enumerate(obj.data.materials):
            if mat==original:
                obj.data.materials[index]=material
        recolored.append(obj.name)
        if obj.name.startswith('PkgGH5Sofa(') and '_seat' in obj.name:
            low,high=_bb(obj)
            for vertex in obj.data.vertices:
                p=obj.matrix_world@vertex.co
                u=(p.y-low[1])/max(.001,high[1]-low[1])
                t=(p.z-low[2])/max(.001,high[2]-low[2])
                delta=.009*math.sin(math.pi*u)**2*t*t
                vertex.co+=obj.matrix_world.to_3x3().inverted()@Vector((0,0,-delta))
            obj.data.update()
            modified.append(obj.name)
        if (obj.name.startswith('PkgGH5Sofa(') and obj.name.endswith('_base')) or (obj.name.startswith('PkgGH5Club(') and obj.name.endswith('_seat')):
            obj.data.materials.append(plinth)
            bm=bmesh.new()
            bm.from_mesh(obj.data)
            local_point=obj.matrix_world.inverted()@Vector((0,0,cut_z))
            local_normal=obj.matrix_world.to_3x3().transposed()@Vector((0,0,1))
            bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=.00001,plane_co=local_point,plane_no=local_normal,clear_inner=False,clear_outer=False)
            for face in bm.faces:
                if (obj.matrix_world@face.calc_center_median()).z<cut_z-.00001:
                    face.material_index=len(obj.data.materials)-1
            bm.to_mesh(obj.data)
            bm.free()
            obj.data.update()
            modified.append(obj.name)
    removed=[o.name for o in pads]
    for obj in pads:
        bpy.data.objects.remove(obj,do_unlink=True)
    scene['pkg_g_H5b_seating_finish']=1
    stats['pkg_g_H5b_seating_finish']={'replaced':removed,'modified':modified,'recolored':recolored,'continuous_curved_backs':len(backs),'gray_rgb':[.24,.24,.23],'seat_compression_max_m':.009,'tables_and_chair_centres_unchanged':True}


def _pkg_g_H5c_banquet_linens(stats):
    """R18 proposal 4: fitted skirts, irregular pleats and open ribbon bows."""
    scene=bpy.context.scene
    if scene.get('pkg_g_H5c_banquet_linens'):
        return
    lo,hi=_room(HALL)
    tables=[o for o in bpy.data.objects if o.type=='MESH' and o.name.startswith('H5Tablecloth') and _in_room(o,lo,hi)]
    chairs=[o for o in bpy.data.objects if o.type=='MESH' and o.name.startswith('Real_hssd') and _in_room(o,lo,hi) and _bb(o)[0][2]<lo[2]+.15 and .45<_bb(o)[1][2]-_bb(o)[0][2]<1.2]
    if len(tables)!=12 or len(chairs)!=48:
        raise ValueError(f'Unexpected banquet counts {len(tables)}/{len(chairs)}')
    fabric=_flat('ir_pkg_g_H5c_white_linen',(.88,.87,.83),.88)
    fs=fabric.node_tree.nodes['Principled BSDF']
    fs.inputs['Sheen Weight'].default_value=.35
    fs.inputs['Emission Strength'].default_value=0
    navy=_flat('ir_pkg_g_H5c_navy_satin',(.03,.08,.19),.40)
    ns=navy.node_tree.nodes['Principled BSDF']
    ns.inputs['Sheen Weight'].default_value=.60
    ns.inputs['Emission Strength'].default_value=0
    def create(name,verts,faces,material,thickness=.0015):
        mesh=bpy.data.meshes.new(name+'Mesh')
        mesh.from_pydata(verts,[],faces)
        mesh.materials.append(material)
        for face in mesh.polygons:
            face.use_smooth=True
        mesh.update()
        obj=bpy.data.objects.new(name,mesh)
        scene.collection.objects.link(obj)
        solid=obj.modifiers.new('Thin fabric edge','SOLIDIFY')
        solid.thickness=thickness
        return obj
    rows=[]
    for index,obj in enumerate(sorted(tables,key=lambda o:o.name)):
        points=[obj.matrix_world@v.co for v in obj.data.vertices]
        top=max(p.z for p in points)
        low,high=_bb(obj)
        cx,cy=(low[0]+high[0])/2,(low[1]+high[1])/2
        radius=max(math.hypot(p.x-cx,p.y-cy) for p in points if p.z>top-.0001)
        verts=[(cx,cy,top)]
        faces=[]
        segments,rings=288,18
        for j in range(rings+1):
            t=j/rings
            for k in range(segments):
                angle=2*math.pi*k/segments
                phase=48*angle+.35*math.sin(5*angle+index)+.20*math.sin(11*angle)
                r=radius+t*t*.035*(.52+.48*math.cos(phase))
                z=top*(1-t)+(lo[2]+.020)*t+.004*math.sin(7*angle+index)*t*t
                verts.append((cx+r*math.cos(angle),cy+r*math.sin(angle),z))
        faces.extend((0,1+k,1+(k+1)%segments) for k in range(segments))
        for j in range(rings):
            for k in range(segments):
                a=1+j*segments+k
                b=1+j*segments+(k+1)%segments
                faces.append((a,a+segments,b+segments,b))
        mesh=bpy.data.meshes.new(obj.name+'_pleated')
        inverse=obj.matrix_world.inverted()
        mesh.from_pydata([tuple(inverse@Vector(p)) for p in verts],[],faces)
        mesh.materials.append(fabric)
        for face in mesh.polygons:
            face.use_smooth=len(face.vertices)==4
        mesh.update()
        obj.data=mesh
        rows.append({'table':obj.name,'centre':[cx,cy],'top_z':top,'radius':radius,'pleats':48})
    chair_rows=[]
    wall_fits=0
    for index,obj in enumerate(sorted(chairs,key=lambda o:o.name)):
        low,high=_bb(obj)
        cx,cy=(low[0]+high[0])/2,(low[1]+high[1])/2
        table=min(rows,key=lambda r:(r['centre'][0]-cx)**2+(r['centre'][1]-cy)**2)
        outward=Vector((cx-table['centre'][0],cy-table['centre'][1],0)).normalized()
        tangent=Vector((-outward.y,outward.x,0))
        points=[obj.matrix_world@v.co for v in obj.data.vertices]
        height=high[2]-low[2]
        lower=[p for p in points if p.z<=low[2]+height*.50]
        ts=[p.dot(tangent) for p in lower]
        ds=[p.dot(outward) for p in lower]
        tc,dc=(min(ts)+max(ts))/2,(min(ds)+max(ds))/2
        width,depth=max(ts)-min(ts)+.040,max(ds)-min(ds)+.040
        section=_pkg_g_H5_section(width,depth,.035,steps=24)
        count=len(section)
        verts=[]
        faces=[]
        def world(t,d,z):
            nonlocal wall_fits
            p=tangent*t+outward*d+Vector((0,0,z))
            bounded=Vector((max(lo[0]+.003,min(hi[0]-.003,p.x)),max(lo[1]+.003,min(hi[1]-.003,p.y)),z))
            if (bounded-p).length>.00001:
                wall_fits+=1
            return tuple(bounded)
        for j in range(15):
            t=j/14
            z=(low[2]+height*.48)*(1-t)+(lo[2]+.030)*t
            for k,(px,py) in enumerate(section):
                phase=20*2*math.pi*k/count+.4*math.sin(k*2*math.pi/count*3+index)
                scale=1+.006*t*t*(.5+.5*math.sin(phase))/max(.05,min(width,depth)/2)
                verts.append(world(tc+px*scale,dc+py*scale,z+.002*math.sin(phase)*t))
        for j in range(14):
            for k in range(count):
                a=j*count+k
                b=j*count+(k+1)%count
                faces.append((a,a+count,b+count,b))
        create(f'PkgGH5cChairSkirt({index})',verts,faces,fabric)
        back=max(p.dot(outward) for p in points)+.012
        bow_z=low[2]+height*.74
        bow_verts=[]
        bow_faces=[]
        for side in (-1,1):
            begin=len(bow_verts)
            for k in range(49):
                a=k*2*math.pi/48
                t=tc+side*.075*(1-math.cos(a))
                d=back+.018*math.sin(a)
                z=bow_z+.050*math.sin(a)
                for edge in (-1,1):
                    bow_verts.append(world(t,d,z+edge*.015))
            for k in range(48):
                a=begin+k*2
                bow_faces.append((a,a+2,a+3,a+1))
            begin=len(bow_verts)
            for k in range(19):
                t=k/18
                for edge in (-1,1):
                    bow_verts.append(world(tc+side*(.025+.055*t)+edge*.018,back+.010+.012*math.sin(2*math.pi*t+index),bow_z-.30*t))
            for k in range(18):
                a=begin+k*2
                bow_faces.append((a,a+2,a+3,a+1))
        create(f'PkgGH5cNavyBow({index})',bow_verts,bow_faces,navy)
        # A narrow satin band follows the existing back, rather than hiding the seat.
        band=[world(min(ts),back,bow_z-.040),world(max(ts),back,bow_z-.040),world(max(ts),back,bow_z+.040),world(min(ts),back,bow_z+.040)]
        create(f'PkgGH5cSatinBand({index})',band,[(0,1,2,3)],navy)
        chair_rows.append({'chair':obj.name,'height':height,'skirt_top':low[2]+height*.48,'hem_z':lo[2]+.030,'bow_z':bow_z,'tail_m':.30})
    old=bpy.data.objects.get('H5R3Sashes')
    removed=[]
    if old is not None:
        removed.append(old.name)
        bpy.data.objects.remove(old,do_unlink=True)
    scene['pkg_g_H5c_banquet_linens']=1
    stats['pkg_g_H5c_banquet_linens']={'tables':rows,'chairs':chair_rows,'modified':[r['table'] for r in rows],'recolored':[r['table'] for r in rows],'replaced':removed,'wall_fitted_vertices':wall_fits,'existing_chair_transforms_unchanged':True}


def _pkg_g_H5c_corridor_finish(stats):
    """R18 proposal 14: alternating timber/fabric, denser dark cloud carpet."""
    scene=bpy.context.scene
    if scene.get('pkg_g_H5c_corridor_finish'):
        return
    wood=bpy.data.materials.new('ir_pkg_g_H5c_corridor_walnut')
    wood.use_nodes=True
    wood['weathered']=True
    nodes,links=wood.node_tree.nodes,wood.node_tree.links
    bs=nodes['Principled BSDF']
    bs.inputs['Roughness'].default_value=.42
    bs.inputs['Coat Weight'].default_value=.15
    bs.inputs['Emission Strength'].default_value=0
    geo=nodes.new('ShaderNodeNewGeometry')
    scale=nodes.new('ShaderNodeVectorMath')
    scale.operation='MULTIPLY'
    scale.inputs[1].default_value=(22,22,.8)
    links.new(geo.outputs['Position'],scale.inputs[0])
    grain=nodes.new('ShaderNodeTexWave')
    grain.wave_type='BANDS'
    grain.bands_direction='X'
    grain.inputs['Scale'].default_value=.65
    grain.inputs['Distortion'].default_value=3
    grain.inputs['Detail'].default_value=4
    links.new(scale.outputs[0],grain.inputs['Vector'])
    tint=nodes.new('ShaderNodeMixRGB')
    tint.inputs[1].default_value=(.20,.11,.04,1)
    tint.inputs[2].default_value=(.42,.27,.13,1)
    links.new(grain.outputs['Fac'],tint.inputs[0])
    links.new(tint.outputs[0],bs.inputs['Base Color'])
    cloth=_flat('ir_pkg_g_H5c_corridor_fabric',(.30,.29,.27),.95)
    cs=cloth.node_tree.nodes['Principled BSDF']
    cs.inputs['Emission Strength'].default_value=0
    cs.inputs['Sheen Weight'].default_value=.15
    pile=cloth.node_tree.nodes.new('ShaderNodeTexNoise')
    pile.inputs['Scale'].default_value=500
    bump=cloth.node_tree.nodes.new('ShaderNodeBump')
    bump.inputs['Distance'].default_value=.0003
    bump.inputs['Strength'].default_value=.18
    cloth.node_tree.links.new(pile.outputs['Fac'],bump.inputs['Height'])
    cloth.node_tree.links.new(bump.outputs[0],cs.inputs['Normal'])
    rows=[]
    for name in ('H5CorrWoodN','H5CorrWoodS'):
        obj=bpy.data.objects.get(name)
        if obj is None:
            raise ValueError('Corridor veneer missing: '+name)
        mesh=obj.data.copy()
        parent=list(range(len(mesh.vertices)))
        def root(i):
            while parent[i]!=i:
                parent[i]=parent[parent[i]]
                i=parent[i]
            return i
        for edge in mesh.edges:
            a,b=edge.vertices
            parent[root(b)]=root(a)
        groups={}
        for i,vertex in enumerate(mesh.vertices):
            groups.setdefault(root(i),[]).append(obj.matrix_world@vertex.co)
        ordered=sorted(groups,key=lambda k:sum(p.x for p in groups[k])/len(groups[k]))
        slots={key:index%2 for index,key in enumerate(ordered)}
        mesh.materials.clear()
        mesh.materials.append(wood)
        mesh.materials.append(cloth)
        for face in mesh.polygons:
            face.material_index=slots[root(face.vertices[0])]
        obj.data=mesh
        rows.append({'object':name,'panel_components':len(groups),'timber':sum(v==0 for v in slots.values()),'fabric':sum(v==1 for v in slots.values()),'geometry_unchanged':True})
    original=bpy.data.materials.get('ir_pkg_g_H5_corridor_carpet')
    if original is None:
        raise ValueError('Metric corridor carpet missing')
    carpet=original.copy()
    carpet.name='ir_pkg_g_H5c_corridor_cloud_carpet'
    shader=carpet.node_tree.nodes['Principled BSDF']
    cream=shader.inputs['Base Color'].links[0].from_node
    brown=cream.inputs[1].links[0].from_node
    cream.inputs[2].default_value=(.64,.55,.43,1)
    brown.inputs[1].default_value=(.13,.08,.055,1)
    brown.inputs[2].default_value=(.28,.19,.125,1)
    for node in carpet.node_tree.nodes:
        if node.type=='MAP_RANGE':
            old=node.inputs['From Min'].default_value
            if abs(old-.3875)<.001:
                node.inputs['From Min'].default_value=.4475
                node.inputs['From Max'].default_value=.4725
            elif abs(old-.5075)<.001:
                node.inputs['From Min'].default_value=.5475
                node.inputs['From Max'].default_value=.5725
    shader.inputs['Roughness'].default_value=.94
    shader.inputs['Emission Strength'].default_value=0
    _set_floor(CORR,carpet)
    scene['pkg_g_H5c_corridor_finish']=1
    stats['pkg_g_H5c_corridor_finish']={'panels':rows,'recolored':['H5CorrWoodN','H5CorrWoodS',CORR+'.floor'],'all_geometry_unchanged':True,'doors_and_border_unchanged':True,'carpet_thresholds':[.46,.56]}


def _pkg_g_H5c_bedding(stats):
    """R18 proposal 15: measured mattress support, compressed pillows and cloth."""
    import bmesh
    from mathutils.bvhtree import BVHTree
    from bedding_cloth import drape_strip
    scene=bpy.context.scene
    if scene.get('pkg_g_H5c_bedding'):
        return
    room='bedroom_0/0'
    lo,hi=_room(room)
    beds=[o for o in bpy.data.objects if o.type=='MESH' and o.name.startswith('SoftBedFactory') and _in_room(o,lo,hi)]
    if len(beds)!=1:
        raise ValueError('Expected one suite bed')
    bed=beds[0]
    _,_,head,_,_,_=_bed_frame(bed)
    h=Vector((head[0],head[1],0))
    cross=Vector((-h.y,h.x,0))
    mesh=bed.data
    parent=list(range(len(mesh.vertices)))
    def root(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]]
            i=parent[i]
        return i
    for edge in mesh.edges:
        a,b=edge.vertices
        parent[root(b)]=root(a)
    components={}
    for i,v in enumerate(mesh.vertices):
        components.setdefault(root(i),[]).append(i)
    face_material={root(face.vertices[0]):mesh.materials[face.material_index].name for face in mesh.polygons}
    candidates=[]
    for key,indices in components.items():
        if face_material.get(key)!='ir_sfb_white_b':
            continue
        points=[bed.matrix_world@mesh.vertices[i].co for i in indices]
        length=max(p.dot(h) for p in points)-min(p.dot(h) for p in points)
        width=max(p.dot(cross) for p in points)-min(p.dot(cross) for p in points)
        height=max(p.z for p in points)-min(p.z for p in points)
        if length*width>1 and .16<height<.45:
            candidates.append((length*width,key,points))
    if not candidates:
        raise ValueError('No separate broad mattress component found')
    _,mattress_key,points=max(candidates,key=lambda row:row[0])
    a0,a1=min(p.dot(h) for p in points),max(p.dot(h) for p in points)
    b0,b1=min(p.dot(cross) for p in points),max(p.dot(cross) for p in points)
    origin=h*((a0+a1)/2)+cross*((b0+b1)/2)
    length,width=a1-a0,b1-b0
    top=max(p.z for p in points)
    keep={key for key in components if key==mattress_key or face_material.get(key) in ('ir_sfb_oak','ir_sfb_cream')}
    kept_before=sorted(tuple(round(x,6) for x in bed.matrix_world@mesh.vertices[i].co) for key in keep for i in components[key])
    replacement=mesh.copy()
    bm=bmesh.new()
    bm.from_mesh(replacement)
    bm.verts.ensure_lookup_table()
    bm.verts.index_update()
    bmesh.ops.delete(bm,geom=[f for f in bm.faces if root(f.verts[0].index) not in keep],context='FACES_ONLY')
    bmesh.ops.delete(bm,geom=[v for v in bm.verts if not v.link_faces],context='VERTS')
    bm.to_mesh(replacement)
    bm.free()
    replacement.update()
    after=sorted(tuple(round(x,6) for x in bed.matrix_world@v.co) for v in replacement.vertices)
    if kept_before!=after:
        raise ValueError('Mattress/frame vertices changed')
    upholstery=_flat('ir_pkg_g_H5c_bed_upholstery',(.42,.36,.29),.86)
    replacement.materials.append(upholstery)
    for face in replacement.polygons:
        material=replacement.materials[face.material_index]
        if material.name in ('ir_sfb_oak','ir_sfb_cream'):
            face.material_index=len(replacement.materials)-1
    bed.data=replacement
    modified=[bed.name]
    dress=bpy.data.objects.get('H5RoomDress('+room+')')
    if dress is not None:
        data=dress.data.copy()
        keep_ids={i for face in data.polygons if data.materials[face.material_index].name!='ir_h5_duvet_w' for i in face.vertices}
        preserved=sorted(tuple(data.vertices[i].co) for i in keep_ids)
        bm=bmesh.new()
        bm.from_mesh(data)
        bmesh.ops.delete(bm,geom=[f for f in bm.faces if data.materials[f.material_index].name=='ir_h5_duvet_w'],context='FACES_ONLY')
        bmesh.ops.delete(bm,geom=[v for v in bm.verts if not v.link_faces],context='VERTS')
        bm.to_mesh(data)
        bm.free()
        data.update()
        if preserved!=sorted(tuple(v.co) for v in data.vertices):
            raise ValueError('Joined room architecture changed')
        dress.data=data
        modified.append(dress.name)
    old=[]
    for obj in list(bpy.data.objects):
        if obj.type!='MESH':
            continue
        named=obj.name in ('H5Duvet('+room+')','H5FootThrow('+room+')') or obj.name.startswith(('H5Pillow('+room+'|','H5Euro('+room+'|'))
        accent=obj.name.startswith('Real_') and 'pillow' in obj.name.lower() and _in_room(obj,lo,hi)
        if accent:
            low,high=_bb(obj)
            p=Vector(((low[0]+high[0])/2,(low[1]+high[1])/2,0))
            accent=abs((p-origin).dot(h))<length/2+.12 and abs((p-origin).dot(cross))<width/2+.12
        if named or accent:
            old.append(obj)
    white=_flat('ir_pkg_g_H5c_cotton',(.88,.87,.83),.90)
    white.node_tree.nodes['Principled BSDF'].inputs['Sheen Weight'].default_value=.20
    cotton_shader=white.node_tree.nodes['Principled BSDF']
    for socket in ('Base Color','Roughness'):
        for link in list(cotton_shader.inputs[socket].links):
            white.node_tree.links.remove(link)
    cotton_shader.inputs['Base Color'].default_value=(.88,.87,.83,1)
    cotton_shader.inputs['Roughness'].default_value=.90
    knit=_flat('ir_pkg_g_H5c_knit',(.25,.22,.18),.95)
    for material,scale,distance in ((white,500,.0003),(knit,320,.0005)):
        nodes,links=material.node_tree.nodes,material.node_tree.links
        shader=nodes['Principled BSDF']
        shader.inputs['Emission Strength'].default_value=0
        geo=nodes.new('ShaderNodeNewGeometry')
        noise=nodes.new('ShaderNodeTexNoise')
        noise.inputs['Scale'].default_value=scale
        links.new(geo.outputs['Position'],noise.inputs['Vector'])
        bump=nodes.new('ShaderNodeBump')
        bump.inputs['Distance'].default_value=distance
        bump.inputs['Strength'].default_value=.18
        links.new(noise.outputs['Fac'],bump.inputs['Height'])
        links.new(bump.outputs[0],shader.inputs['Normal'])
    def world(a,b,z):
        p=origin+h*a+cross*b
        return (p.x,p.y,z)
    def wrinkles(a,b):
        return .012+.030*math.sin(7*a+3*b)**2+.012*math.sin(17*b-4*a)**2
    shoulder=.060
    hang=.23
    def round_edge(v,half):
        if abs(v)<=half-shoulder:
            return v,0
        sign=-1 if v<0 else 1
        s=abs(v)-(half-shoulder)
        angle=min(math.pi/2,s/shoulder)
        distance=half-shoulder+shoulder*math.sin(angle)
        drop=shoulder*(1-math.cos(angle))+max(0,s-math.pi*shoulder/2)
        return sign*distance,drop
    head_end=length/2-.38
    verts=[]
    faces=[]
    na,nb=112,100
    for i in range(na+1):
        a=-length/2-hang+(head_end+length/2+hang)*i/na
        aa,foot_drop=round_edge(a,length/2) if a<0 else (a,0)
        for j in range(nb+1):
            b=-width/2-hang+(width+2*hang)*j/nb
            bb,side_drop=round_edge(b,width/2)
            z=top+wrinkles(aa,bb)-max(foot_drop,side_drop)
            edge=max(foot_drop,side_drop)/hang
            bb+=.009*math.sin(13*a+2)*min(1,edge)
            verts.append(world(aa,bb,z))
    for i in range(na):
        for j in range(nb):
            a=i*(nb+1)+j
            faces.append((a,a+nb+1,a+nb+2,a+1))
    # This bed frame uses across = head rotated +90 degrees, so the grid is upward.
    data=bpy.data.meshes.new('PkgGH5cSuiteDuvetMesh')
    data.from_pydata(verts,[],faces)
    data.materials.append(white)
    for face in data.polygons:
        face.use_smooth=True
    data.update()
    duvet=bpy.data.objects.new('PkgGH5cSuiteDuvet',data)
    scene.collection.objects.link(duvet)
    solid=duvet.modifiers.new('10mm soft duvet','SOLIDIFY')
    solid.thickness=.010
    solid.offset=-1
    bvh=BVHTree.FromPolygons([Vector(p) for p in verts],faces,all_triangles=False)
    def support(a,b):
        x,y,_=world(a,b,0)
        hit,_,_,_=bvh.ray_cast(Vector((x,y,top+3)),Vector((0,0,-1)),5)
        return hit.z if hit is not None else top
    pillow_rows=[]
    for index,b in enumerate((-width/4,width/4)):
        a=length/2-.27
        bm=bmesh.new()
        result=bmesh.ops.create_uvsphere(bm,u_segments=64,v_segments=32,radius=1)
        angle=math.radians(15)
        for vertex in result['verts']:
            p=vertex.co.copy()
            x=.225*math.copysign(abs(p.x)**.43,p.x)
            y=.325*math.copysign(abs(p.y)**.43,p.y)
            z=.080*p.z
            aa=x*math.cos(angle)-z*math.sin(angle)
            zz=x*math.sin(angle)+z*math.cos(angle)
            vertex.co=world(a+aa,b+y,top+zz)
        shift=max(support((v.co-origin).dot(h),(v.co-origin).dot(cross))+.003-v.co.z for v in bm.verts)
        for vertex in bm.verts:
            vertex.co.z+=shift
        pd=bpy.data.meshes.new('PkgGH5cPillowMesh'+str(index))
        bm.to_mesh(pd)
        bm.free()
        pd.materials.append(white)
        for face in pd.polygons:
            face.use_smooth=True
        pd.update()
        obj=bpy.data.objects.new('PkgGH5cCompressedPillow('+str(index)+')',pd)
        scene.collection.objects.link(obj)
        gap=min(v.co.z-support((v.co-origin).dot(h),(v.co-origin).dot(cross)) for v in pd.vertices)
        pillow_rows.append({'object':obj.name,'minimum_support_gap_m':gap,'size_m':[.45,.65,.16],'tilt_deg':15})
    class SupportRay:
        half_span=width/2
        def point(self,across,along,z_offset):
            return Vector(world(-length/2+.38+along,across,z_offset))
        def __call__(self,across,along):
            p=self.point(across,along,0)
            hit,_,_,_=bvh.ray_cast(Vector((p.x,p.y,top+3)),Vector((0,0,-1)),5)
            return hit
    ray=SupportRay()
    runner=drape_strip(ray,.50,width+.48,.22)
    runner.name='PkgGH5cSuiteRunner'
    if runner.name not in scene.collection.objects:
        scene.collection.objects.link(runner)
    for collection in list(runner.users_collection):
        if collection!=scene.collection:
            collection.objects.unlink(runner)
    runner.data.materials.append(knit)
    gaps=[]
    for index in runner['contact_vertices']:
        p=runner.data.vertices[index].co
        a=(p-origin).dot(h)
        b=(p-origin).dot(cross)
        gaps.append(p.z-support(a,b))
    removed=[obj.name for obj in old]
    for obj in old:
        bpy.data.objects.remove(obj,do_unlink=True)
    scene['pkg_g_H5c_bedding']=1
    stats['pkg_g_H5c_bedding']={'room':room,'modified':modified,'recolored':[bed.name],'replaced':removed,'mattress_top_z':top,'mattress_size_m':[length,width],'mattress_frame_vertices_preserved':len(kept_before),'head_direction':list(head),'pillows':pillow_rows,'runner_support_gap_m':[min(gaps),max(gaps)],'other_bedrooms_unchanged':True}


def _pkg_g_H5c_chandeliers(stats):
    """R18 proposal 6: dense gold/crystal bodies without an opaque core globe."""
    import bmesh
    scene=bpy.context.scene
    if scene.get('pkg_g_H5c_chandeliers'):
        return
    old=[bpy.data.objects.get(name) for name in ('H5R3Chandelier49','H5R3Chandelier54')]
    if any(obj is None for obj in old):
        raise ValueError('Expected the two existing banquet chandeliers')
    brass=_plain_metal('ir_pkg_g_H5c_chandelier_gold',(.65,.44,.17),.20)
    glass=bpy.data.materials.new('ir_pkg_g_H5c_cut_crystal')
    glass.use_nodes=True
    glass['weathered']=True
    gs=glass.node_tree.nodes['Principled BSDF']
    gs.inputs['Base Color'].default_value=(.96,.95,.92,1)
    gs.inputs['Transmission Weight'].default_value=1
    gs.inputs['IOR'].default_value=1.5
    gs.inputs['Roughness'].default_value=.03
    bulb=bpy.data.materials.new('ir_pkg_g_H5c_chandelier_bulb')
    bulb.use_nodes=True
    bulb['weathered']=True
    bs=bulb.node_tree.nodes['Principled BSDF']
    bs.inputs['Emission Color'].default_value=(1,.68,.34,1)
    bs.inputs['Emission Strength'].default_value=2
    rows=[]
    for index,previous in enumerate(old):
        lo,hi=_bb(previous)
        cx,cy=(lo[0]+hi[0])/2,(lo[1]+hi[1])/2
        hub=Vector((cx,cy,2.75))
        bm=bmesh.new()
        rg=random.Random(8600+index)
        def rod(a,b,radius,slot=0):
            a,b=Vector(a),Vector(b)
            direction=b-a
            result=bmesh.ops.create_cone(bm,cap_ends=True,segments=6,radius1=radius,radius2=radius,depth=direction.length)
            verts=result['verts']
            bmesh.ops.transform(bm,matrix=direction.to_track_quat('Z','Y').to_matrix().to_4x4(),verts=verts)
            bmesh.ops.translate(bm,vec=(a+b)/2,verts=verts)
            for face in {f for v in verts for f in v.link_faces}:
                face.material_index=slot
        def bead(point,radius,slot=1):
            result=bmesh.ops.create_icosphere(bm,subdivisions=1,radius=radius)
            verts=result['verts']
            bmesh.ops.scale(bm,vec=(1,1,1.30),verts=verts)
            bmesh.ops.translate(bm,vec=point,verts=verts)
            for face in {f for v in verts for f in v.link_faces}:
                face.material_index=slot
        rod((cx,cy,3.62),(cx,cy,2.75),.010)
        rod((cx,cy,3.60),(cx,cy,3.64),.065)
        body_bottom,body_top=9.0,0.0
        for k in range(450):
            z=-1+2*(k+.5)/450
            angle=k*2.399963+index*.6
            radial=math.sqrt(1-z*z)
            direction=Vector((radial*math.cos(angle),radial*math.sin(angle),z*.62))
            length=rg.uniform(.69,.86)
            endpoint=hub+direction*length
            body_bottom=min(body_bottom,endpoint.z-.028)
            body_top=max(body_top,endpoint.z+.028)
            rod(hub+direction*.10,endpoint,.0023)
            for fraction in (.63,.82,1):
                bead(hub+direction*(length*fraction),rg.uniform(.014,.021))
        for k in range(18):
            angle=k*2.399963
            point=hub+Vector((.12*math.cos(angle),.12*math.sin(angle),.10*math.sin(k*1.7)))
            bead(point,.006,2)
        mesh=bpy.data.meshes.new('PkgGH5cCrystalMesh'+str(index))
        bm.to_mesh(mesh)
        bm.free()
        for material in (brass,glass,bulb):
            mesh.materials.append(material)
        mesh.update()
        obj=bpy.data.objects.new('PkgGH5cCrystalChandelier('+str(index)+')',mesh)
        scene.collection.objects.link(obj)
        bpy.context.view_layer.update()
        low,high=_bb(obj)
        if low[2]<2.15 or high[2]>3.66:
            raise ValueError('Chandelier height limit violated')
        coffer=bpy.data.objects.get('H5R3HallCoffer')
        coffer_bottom=_bb(coffer)[0][2] if coffer else 3.335
        if body_top>coffer_bottom-.02 or body_bottom<2.15:
            raise ValueError('Crystal body intersects coffer or head-clearance limit')
        rows.append({'body_top_z':body_top,'coffer_clearance_m':coffer_bottom-body_top,'object':obj.name,'centre_xy':[cx,cy],'rods':450,'crystal_beads':1350,'tiny_bulbs':18,'min_z':low[2],'max_z':high[2],'opaque_core_globe':False})
    removed=[obj.name for obj in old]
    for obj in old:
        bpy.data.objects.remove(obj,do_unlink=True)
    scene['pkg_g_H5c_chandeliers']=1
    stats['pkg_g_H5c_chandeliers']={'fixtures':rows,'replaced':removed,'existing_point_lights_unchanged':True,'ordinary_crystal_emission':0}


def _pkg_g_H5room01_live(stats):
    """Default-on approved break-room upgrade, including existing kit scenes."""
    if bpy.context.scene.get("pkg_g_H5room01"):
        return 0
    import hotel5_room01_candidate
    world = bpy.context.scene.world
    try:
        result = hotel5_room01_candidate.apply()
    finally:
        bpy.context.scene.world = world
    result["shared_world_preserved"] = True
    result["live_integration"] = True
    stats["pkg_g_H5room01_live"] = result
    return 1


def apply(stats):
    sc = bpy.context.scene
    if bpy.data.objects.get(f"{LOUNGE}.floor") is None:
        return 0
    if sc.get("ir_hotel5_shell"):
        try:
            return _pkg_g_H5room01_live(stats)
        except Exception as ex:
            import traceback
            traceback.print_exc()
            stats["h5_pkg_g_H5room01_live_error"] = repr(ex)[:160]
            return 0
    skip = set((os.environ.get("ROOM_HOTEL5_SKIP") or "").split(",")); n = 0
    for key, fn in (("clean", _clean), ("lounge", _lounge), ("elev", _elev), ("corr", _corr), ("beds", _beds), ("spare", _bed_spare), ("ensuite", _ensuites), ("stalls", _stalls), ("kitchen", _kitchen), ("lobby", _lobby), ("hall", _hall), ("rooms2", _rooms_dress), ("lounge2", _lounge_groups), ("lifts", _lifts), ("corr2", _corr2), ("ensuite2", _ensuite_full), ("guests", _guests), ("stalls2", _stalls2), ("bedwalls", _bed_walls), ("banq2", _banq2), ("lobby2", _lobby2), ("finish", _finish), ("windows", _windows), ("vary", _vary), ("ratio3", _ratio3), ("pkg_g_H5_lounge_seating", _pkg_g_H5_lounge_seating), ("pkg_g_H5_elevator_finish", _pkg_g_H5_elevator_finish), ("pkg_g_H5_sea_mapping", _pkg_g_H5_sea_mapping), ("pkg_g_H5_banquet_carpet", _pkg_g_H5_banquet_carpet), ("pkg_g_H5_corridor_carpet", _pkg_g_H5_corridor_carpet), ("pkg_g_H5b_lobby_wall", _pkg_g_H5b_lobby_wall), ("pkg_g_H5b_inlay", _pkg_g_H5b_inlay), ("pkg_g_H5b_columns", _pkg_g_H5b_columns), ("pkg_g_H5b_palms", _pkg_g_H5b_palms), ("pkg_g_H5b_lobby_coffers", _pkg_g_H5b_lobby_coffers), ("pkg_g_H5b_hall_bays", _pkg_g_H5b_hall_bays), ("pkg_g_H5b_bouquets", _pkg_g_H5b_bouquets), ("pkg_g_H5b_seating_finish", _pkg_g_H5b_seating_finish), ("pkg_g_H5c_banquet_linens", _pkg_g_H5c_banquet_linens), ("pkg_g_H5c_corridor_finish", _pkg_g_H5c_corridor_finish), ("pkg_g_H5c_bedding", _pkg_g_H5c_bedding), ("pkg_g_H5c_chandeliers", _pkg_g_H5c_chandeliers), ("pkg_g_H5room01_live", _pkg_g_H5room01_live)):
        if key in skip:
            continue
        try:
            bpy.context.view_layer.update(); fn(stats); n += 1
        except Exception as ex:                                  # noqa: BLE001 -- a part that fails must not sink the kit stage
            import traceback; traceback.print_exc()
            stats[f"h5_{key}_error"] = repr(ex)[:160]
    stats["real_assets"] = {k_: list(v_) for k_, v_ in ra.STATS.items()}
    sc["ir_hotel5_shell"] = 1
    return n
