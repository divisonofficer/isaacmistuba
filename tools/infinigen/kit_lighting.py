"""Light a furnished room from its style kit (non-home 20, 2026-10-16: 'warm, layered light became uniform room light' -- the kit's
colour temperature, ambient level, daylight and accent lights are applied together, never one at a time).

    python kit_lighting.py IN.blend --out OUT.blend --plans plans.json --seed N

Reads plans.json['style_spec']['lighting'] (from room_planner.reference): colour_temp_k tints every interior light and emissive
fixture, ambient scales fixture energy, accents add wall sconces and table candles, and the daylight level is stored on the scene
(scene['ir_daylight']) for the renderer to scale window light and the sky. No kit lighting: the file is saved unchanged.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import room_dressing as rd  # noqa: E402
from room_planner import proc_assets as pa  # noqa: E402

AMBIENT = {"low": 0.35, "medium": 1.0, "high": 1.4}


def kelvin_rgb(k: float):
    """Approximate black-body colour (Tanner Helland), linear-ish 0-1."""
    t = k / 100.0
    r = 1.0 if t <= 66 else min(1.0, 1.292936 * (t - 60) ** -0.1332047592)
    g = (0.39008157 * math.log(t) - 0.63184144) if t <= 66 else 1.129890861 * (t - 60) ** -0.0755148492
    b = 1.0 if t >= 66 else (0.0 if t <= 19 else 0.54320678 * math.log(t - 10) - 1.19625408)
    # mild linearisation + 10% white: gamma 2.2 turned 2300 K into (1, 0.31, 0.03) and the ablation came out +11 b* warmer than its
    # reference (floral_moody s2/s3, 2026-10-16)
    # and 30% toward white: a photo is white-balanced; the raw tint left a peach/pink cast in 3 of 4 cafe style evals (G, d_warmth +4..+6.5)
    return tuple(0.7 * (0.9 * max(0.0, min(1.0, c)) ** 1.4 + 0.1) + 0.3 for c in (r, g, b))


def is_window_light(o):
    return o.parent is not None and "Window" in o.parent.name


def sconce(i, warm):
    """A wall sconce (front +X, mounted on the wall): a back plate, an arm and a glowing shade, plus a point light."""
    brass = pa._flat("ir_sconce_metal", (0.55, 0.38, 0.12), 0.3, 1.0)
    glow = pa._flat("ir_sconce_glow", (1.0, 0.85, 0.65), 0.3)
    b = glow.node_tree.nodes["Principled BSDF"]
    b.inputs["Emission Color"].default_value = (*warm, 1); b.inputs["Emission Strength"].default_value = 8.0
    o = pa._prims(f"WallSconceFactory({i}).spawn_asset({i})",
                  [(brass, [("box", (0.01, 0, 0), (0.02, 0.1, 0.16), (0, 0, 0)), ("box", (0.09, 0, 0.04), (0.16, 0.02, 0.02), (0, 0, 0))]),
                   (glow, [("cyl", (0.17, 0, 0.06), (0.05, 0.07, 0.12), (0, 0, 0))])])
    return o


def candle(i, warm):
    wax = pa._flat("ir_candle_glass", (0.9, 0.85, 0.75), 0.2, transmission=0.6)
    flame = pa._flat("ir_flame", (1.0, 0.7, 0.3), 0.3)
    b = flame.node_tree.nodes["Principled BSDF"]
    b.inputs["Emission Color"].default_value = (1.0, 0.62, 0.25, 1); b.inputs["Emission Strength"].default_value = 15.0
    return pa._prims(f"CandleFactory({i}).spawn_asset({i})", [(wax, [("cyl", (0, 0, 0.04), (0.035, 0.035, 0.08), (0, 0, 0))]),
                                                              (flame, [("cyl", (0, 0, 0.095), (0.006, 0.001, 0.025), (0, 0, 0))])])


def add_point(name, at, energy, color, radius=0.05):
    ld = bpy.data.lights.new(name, "POINT"); ld.energy = energy; ld.color = color; ld.shadow_soft_size = radius
    lo = bpy.data.objects.new(f"PointLampFactory(kit).spawn_asset({name})", ld)
    bpy.context.scene.collection.objects.link(lo); lo.location = at
    return lo


def street_backdrop(stats):
    """A street outside every shop front (a panoramic window >= 4 m): pavement, road and the building opposite with its windows.
    Through the glass the bare sky rendered pure white, so the glazing read as a white panelled wall (floor I r21: 'no storefront,
    no glass, no entrance', 3 of 3) -- the same in the cafés."""
    floors = [p_["floor"] for p_ in rd._rooms().values() if "floor" in p_]
    if not floors:
        return
    pts = [f.matrix_world @ Vector(c) for f in floors for c in f.bound_box]
    cx, cy, fz = (min(q.x for q in pts) + max(q.x for q in pts)) / 2, (min(q.y for q in pts) + max(q.y for q in pts)) / 2, max(q.z for q in pts)
    pave = pa._flat("ir_street_pavement", (0.42, 0.41, 0.39), 0.85); road = pa._flat("ir_street_asphalt", (0.09, 0.09, 0.1), 0.8)
    kerb = pa._flat("ir_street_kerb", (0.6, 0.6, 0.58), 0.7); brick = pa._flat("ir_street_facade", (0.36, 0.24, 0.17), 0.85)
    glass = pa._flat("ir_street_glass", (0.03, 0.035, 0.045), 0.08, 0.6); trim = pa._flat("ir_street_trim", (0.75, 0.73, 0.68), 0.6)
    n = 0
    gl = pa._flat("ir_shopfront_glass", (0.92, 0.94, 0.95), 0.02, transmission=1.0)
    fr_ = bpy.data.materials.get("ir_office_door_frame") or pa._flat("ir_shopfront_frame", (0.3, 0.31, 0.33), 0.4, 0.8)
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("WindowFactory(")]:
        if not any(o.data.materials):                            # the runtime's panoramic window comes with no material at all and
            # rendered as an opaque white slab -- the shop front read as 'a white panelled wall' (floor I r21, 3 of 3): big faces glass,
            # the rest frame
            o.data.materials.clear(); o.data.materials.append(fr_); o.data.materials.append(gl)
            for f in o.data.polygons:
                f.material_index = 1 if f.area > 0.25 else 0
            stats["windows_glazed"] = stats.get("windows_glazed", 0) + 1
    if os.environ.get("ROOM_ENV_WINDOWS") == "1":                # the photo panorama of env_windows replaces this procedural street (its kerb / road bands showed as hard edges: S6 r11 ENV-01)
        return
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("WindowFactory(")]:
        d = o.dimensions; along_x = d.x >= d.y; W = max(d.x, d.y)
        if W < 4.0:
            continue
        c = o.matrix_world.translation
        out = Vector((0, -1 if c.y < cy else 1, 0)) if along_x else Vector((-1 if c.x < cx else 1, 0, 0))
        L = W + 30.0
        parts_p = [("box", (2.0, 0, -0.06), (4.0, L, 0.12), (0, 0, 0))]
        parts_k = [("box", (4.05, 0, -0.03), (0.15, L, 0.18), (0, 0, 0))]
        parts_r = [("box", (8.5, 0, -0.1), (9.0, L, 0.1), (0, 0, 0)), ("box", (15.0, 0, -0.06), (4.0, L, 0.12), (0, 0, 0))]
        parts_b = [("box", (17.5, 0, 6.0), (1.0, L, 12.0), (0, 0, 0))]
        parts_g, parts_t = [], []
        for j in range(int(L / 3.0)):
            y = -L / 2 + 1.5 + j * 3.0
            parts_g.append(("box", (16.98, y, 1.6), (0.05, 2.6, 2.6), (0, 0, 0)))       # ground-floor shop windows
            parts_t.append(("box", (16.97, y, 3.1), (0.06, 2.9, 0.25), (0, 0, 0)))
            for z in (5.0, 8.2):
                parts_g.append(("box", (16.98, y, z), (0.05, 1.3, 1.7), (0, 0, 0)))
                parts_t.append(("box", (16.97, y, z - 0.95), (0.08, 1.5, 0.12), (0, 0, 0)))
        b = pa._prims(f"ir_street_backdrop_{n}", [(pave, parts_p), (kerb, parts_k), (road, parts_r), (brick, parts_b), (glass, parts_g),
                                                  (trim, parts_t)])
        b.location = (c.x if along_x else c.x, c.y if not along_x else c.y, fz)
        b.location += out * 0.15
        b.rotation_euler.z = math.atan2(out.y, out.x)
        n += 1
    stats["street_backdrops"] = n


def service_room_lights(stats, clinic=False):
    """Ceiling fixtures in restrooms, stockrooms, changing and staff rooms become flush LED panels: the Infinigen ceiling light drew
    'a residential crystal flush-mount' and 'an industrial dome' (floor H r15, 3 of 3). The fixture's own light sources stay."""
    import bmesh
    boxes = []
    for nm, parts in rd._rooms().items():
        if nm.split("_")[0] in ("restroom", "utility", "closet", "kitchen", "bathroom") + (("office",) if clinic else ()) and "floor" in parts:
            # + a clinic's offices: a black industrial pendant under the grid ceiling read as 'a café or loft' (floor D3 r22, 3 of 3)
            pts = [parts["floor"].matrix_world @ Vector(c) for c in parts["floor"].bound_box]
            boxes.append((min(q.x for q in pts), max(q.x for q in pts), min(q.y for q in pts), max(q.y for q in pts)))
    panel = pa._flat("ir_led_panel", (0.95, 0.95, 0.93), 0.3)
    b = panel.node_tree.nodes["Principled BSDF"]
    b.inputs["Emission Color"].default_value = (1.0, 0.98, 0.95, 1); b.inputs["Emission Strength"].default_value = 4.0
    trim = pa._flat("ir_ac_white", (0.86, 0.86, 0.85), 0.4)
    n = 0
    for o in list(bpy.data.objects):
        if o.type != "MESH" or o.name.split("(")[0] not in ("CeilingLightFactory", "AboCeilingFixtureFactory") or \
                (o.parent is not None and o.parent.type == "MESH"):    # the activity pass hangs ABO fixtures (floor H r15)
            continue
        pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
        cx, cy, top = sum(q.x for q in pts) / 8, sum(q.y for q in pts) / 8, max(q.z for q in pts)
        if not any(b_[0] < cx < b_[1] and b_[2] < cy < b_[3] for b_ in boxes):
            continue
        Minv = o.matrix_world.inverted()
        bm = bmesh.new()
        drop = 0.0                                       # flush again: hung 0.4 m they read as 'pendants on long rods that clash' (J r20,
        # 3 of 3) and still never entered G's frames; was: hung on rods: flush at the ceiling it never entered a corner probe's frame --
        # 'no ceiling lights in any back room' (floor G r30, 3 of 3)
        for slot, (hz, half, dz) in enumerate(((0.04, 0.31, 0.02 + drop), (0.012, 0.28, 0.046 + drop))):   # white frame, then the glowing
            r = bmesh.ops.create_cube(bm, size=1.0)                                                         # diffuser below it
            for v in r["verts"]:
                v.co = Minv @ Vector((cx + v.co.x * 2 * half, cy + v.co.y * 2 * half, top - dz + v.co.z * hz))
            for fc in {fc for v in r["verts"] for fc in v.link_faces}:
                fc.material_index = slot
        for kx in (1, -1):
            r = bmesh.ops.create_cube(bm, size=1.0)
            for v in r["verts"]:
                v.co = Minv @ Vector((cx + kx * 0.22 + v.co.x * 0.012, cy + v.co.y * 0.012, top - drop / 2 + v.co.z * drop))
            for fc in {fc for v in r["verts"] for fc in v.link_faces}:
                fc.material_index = 0
        me = bpy.data.meshes.new(f"ir_led_panel_{n}"); bm.to_mesh(me); bm.free()
        me.materials.append(trim); me.materials.append(panel)
        o.data = me
        for ch in o.children_recursive:                      # a glTF fixture's other parts
            if ch.type == "MESH":
                ch.hide_render = True; ch.hide_viewport = True
        n += 1
    stats["service_led_panels"] = n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("blend"); ap.add_argument("--out", required=True); ap.add_argument("--plans", required=True)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])
    bpy.ops.wm.open_mainfile(filepath=a.blend)
    spec = json.loads(Path(a.plans).read_text()).get("style_spec") or {}
    L = spec.get("lighting")
    stats = {}
    import provenance                                           # src tags + reference-authoritative gating (tools/infinigen/provenance.py)
    provenance.configure(json.loads(Path(a.plans).read_text()))
    _kit_before = set(bpy.data.objects.keys())
    if L:
        rng = random.Random(a.seed)
        kk = L.get("color_temp_k", 3000)
        if spec.get("venue") in ("clinic-reception", "exam-room", "dental-room", "physio-room", "pharmacy"):                          # a clinic is lit neutral whatever its reference's mood
            kk = max(kk, 3800)                                   # (clinic r10: a 2800 K 'spa' kit read as a café or lounge)
        warm = kelvin_rgb(kk)
        amb = AMBIENT.get(L.get("ambient", "medium"), 1.0)
        n = 0
        key = 5.0 if L.get("key_fixture") == "track_spots" else 1.0   # the key fixture carries the room (shop r3: a track-lit boutique
        for o in bpy.data.objects:                               # rendered near black at the default 12 W per spot)
            if o.type == "LIGHT" and not is_window_light(o):
                o.data.color = warm; o.data.energy *= amb * (key if o.data.name.startswith("ir_track_spot") else 1.0); n += 1
        for m in bpy.data.materials:                          # emissive fixtures glow in the same colour
            if m.use_nodes and "Principled BSDF" in m.node_tree.nodes:
                b = m.node_tree.nodes["Principled BSDF"]
                if b.inputs["Emission Strength"].default_value > 0.5 and m.name.startswith(("ir_led", "ir_lamp", "shader_lamp")):
                    b.inputs["Emission Color"].default_value = (*warm, 1)
        stats["lights_tinted"] = n
        scene, deps = bpy.context.scene, bpy.context.evaluated_depsgraph_get()
        acc = set(L.get("accents") or [])
        if "wall_sconces" in acc:                               # 3-6 sconces at 1.9 m on free wall spots
            k = 0
            for name, room in rd._rooms().items():
                if "floor" not in room or "wall" not in room:
                    continue
                fz = max((room["floor"].matrix_world @ Vector(c)).z for c in room["floor"].bound_box)
                for p, nrm in rd._wall_spots(scene, deps, room, rng, fz + 1.9)[: rng.randint(3, 6)]:
                    o = sconce(k, warm)
                    o.rotation_euler = (0, 0, math.atan2(nrm.y, nrm.x)); o.location = p + nrm * 0.01
                    add_point(f"sconce{k}", p + nrm * 0.2 + Vector((0, 0, 0.06)), 25.0 * max(amb, 0.6), warm, 0.06)
                    k += 1
            stats["sconces"] = k
        if "candles" in acc:                                    # a candle on most café / dining tables
            k = 0
            for o in list(bpy.data.objects):
                f = rd._factory(o.name)
                if o.type == "MESH" and f in ("CafeTableFactory", "BreakTableFactory", "TableDiningFactory") and rng.random() < 0.8:
                    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
                    top = max(p.z for p in pts); cx = sum(p.x for p in pts) / 8; cy = sum(p.y for p in pts) / 8
                    c = candle(k, warm); c.location = (cx + rng.uniform(-0.1, 0.1), cy + rng.uniform(-0.1, 0.1), top)
                    add_point(f"candle{k}", Vector((c.location.x, c.location.y, top + 0.12)), 3.0, (1.0, 0.55, 0.22), 0.02)
                    k += 1
            stats["candles"] = k
    # staff rooms inside a high hall get a suspended ceiling at 2.8 m: they kept the 5 m warehouse height and read as 'tall empty cells cut
    # out of the hall' (floor J r11, 3 of 3); their fixtures and lights come down under it
    tile = pa._flat("ir_drop_ceiling", (0.88, 0.88, 0.86), 0.8)
    n_drop = 0
    for name, room in rd._rooms().items():
        if "floor" not in room or "wall" not in room or name.split("_")[0] in ("warehouse", "garage"):
            continue
        pts = [room["floor"].matrix_world @ Vector(c) for c in room["floor"].bound_box]
        fz = max(p.z for p in pts)
        top = max((room["wall"].matrix_world @ Vector(c)).z for c in room["wall"].bound_box)
        if top - fz < 3.6:
            continue
        x0, x1 = min(p.x for p in pts), max(p.x for p in pts); y0, y1 = min(p.y for p in pts), max(p.y for p in pts)
        if (x1 - x0) * (y1 - y0) > 120:                          # a hall keeps its own ceiling: the flagship boutique's exposed services were
            continue                                             # hidden under one 340 m2 suspended slab (first run, 2026-10-17)
        zc = fz + 2.8
        pa._parts_object(f"DropCeilingFactory({n_drop}).spawn_asset({n_drop})", [(tile, [((x0 + x1) / 2, (y0 + y1) / 2, zc + 0.015, x1 - x0, y1 - y0, 0.03)])])
        moved = []
        for o in list(bpy.data.objects):
            if o.parent is not None or not (o.type == "LIGHT" or "Ceiling" in o.name or "LampFactory" in o.name):
                continue
            t = o.matrix_world.translation
            if x0 <= t.x <= x1 and y0 <= t.y <= y1 and t.z > zc:
                o.location.z -= (t.z - (zc - 0.06))
                if o.type == "LIGHT":
                    moved.append(o.matrix_world.translation.copy())
        # a bare light under the tiles glowed 'from nowhere' (floor J r14: office and break-room ceilings, 3 of 3): a flush panel at each
        fix_xy = [o.matrix_world.translation.xy for o in bpy.data.objects if o.type == "MESH" and "Ceiling" in o.name.split("(")[0]
                  and not o.name.startswith("DropCeiling")]
        led = pa._flat("ir_led_panel", (0.95, 0.95, 0.93), 0.3)
        bb = led.node_tree.nodes["Principled BSDF"]
        bb.inputs["Emission Color"].default_value = (1.0, 0.98, 0.95, 1); bb.inputs["Emission Strength"].default_value = 4.0
        for k, q in enumerate(moved):
            if not any((q.xy - f).length < 0.6 for f in fix_xy):
                pa._parts_object(f"CeilingLightFactory(drop{n_drop}_{k}).spawn_asset(d{n_drop}_{k})", [(led, [(q.x, q.y, zc - 0.012, 0.6, 0.6, 0.025)])])
                fix_xy.append(q.xy.copy())
        n_drop += 1
    stats["drop_ceilings"] = n_drop
    # lights buried in architecture: a ceiling fixture placed after the exposed ducts/beams ended up inside a duct, 2 cm of metal under
    # the bulb (floor H r4: the restroom read near black, 3 of 3) -- drop the light just below whatever covers it
    sc_, dg_ = bpy.context.scene, bpy.context.evaluated_depsgraph_get()
    n_unburied = 0
    for o in [o for o in bpy.data.objects if o.type == "LIGHT" and not is_window_light(o)]:
        p = o.matrix_world.translation.copy()
        h = sc_.ray_cast(dg_, p, Vector((0, 0, -1)), distance=0.15)
        if not h[0] or h[4].name.endswith(".floor"):
            continue
        cover, q, z = h[4], h[1], None
        for _ in range(8):                                       # march down through the cover's faces to its underside
            z = q.z
            q = q - Vector((0, 0, 0.003))
            h = sc_.ray_cast(dg_, q, Vector((0, 0, -1)), distance=0.6)
            if not h[0] or h[4] != cover:
                break
            q = h[1]
        m = o.matrix_world.copy(); m.translation.z = z - 0.08; o.matrix_world = m
        n_unburied += 1
    stats["lights_unburied"] = n_unburied
    # service rooms on a floor scene get a neutral ceiling light when none is inside them (floor G: the restroom and stockroom behind a
    # low-ambient café rendered near black -- the fixture pass lights the planned public rooms only)
    lit = [(o.matrix_world.translation, o.data.energy) for o in bpy.data.objects if o.type == "LIGHT" and not is_window_light(o)
           and "(track)" not in o.name]          # track spots aim at the hub's walls; the architecture pass ran them across the whole
                                                  # floor box, over the back rooms (floor G)
    n_svc = 0
    for name, room in rd._rooms().items():
        if "floor" not in room or not name.split("_")[0] in ("restroom", "utility", "kitchen", "closet", "hallway"):
            continue
        pts = [room["floor"].matrix_world @ Vector(c) for c in room["floor"].bound_box]
        x0, x1 = min(p.x for p in pts), max(p.x for p in pts); y0, y1 = min(p.y for p in pts), max(p.y for p in pts)
        fz = max(p.z for p in pts)
        ceil = max((room["wall"].matrix_world @ Vector(c)).z for c in room["wall"].bound_box) if "wall" in room else fz + 2.7
        for o in bpy.data.objects:                       # under a suspended ceiling
            if o.name.startswith("DropCeilingFactory"):
                ps_ = [o.matrix_world @ Vector(c) for c in o.bound_box]
                cx_, cy_ = sum(q.x for q in ps_) / 8, sum(q.y for q in ps_) / 8
                if x0 <= cx_ <= x1 and y0 <= cy_ <= y1:
                    ceil = min(ceil, min(q.z for q in ps_))
        cz = ceil - 0.25
        fixture = any(o.type == "MESH" and ("Ceiling" in o.name.split("(")[0] or o.data.name.startswith("ir_led_panel")) and not o.name.startswith("DropCeiling")
                      and x0 <= o.matrix_world.translation.x <= x1 and y0 <= o.matrix_world.translation.y <= y1 for o in bpy.data.objects)
        if not fixture:                          # a visible flush panel: back rooms lit 'from nowhere' (floor G r16, 3 of 3)
            led = pa._flat("ir_led_panel", (0.95, 0.95, 0.93), 0.3)
            bb = led.node_tree.nodes["Principled BSDF"]
            bb.inputs["Emission Color"].default_value = (1.0, 0.98, 0.95, 1); bb.inputs["Emission Strength"].default_value = 4.0
            hous = pa._flat("ir_batten_housing", (0.55, 0.56, 0.58), 0.4, 0.6)
            cx_, cy_, Lb = (x0 + x1) / 2, (y0 + y1) / 2, min(1.2, 0.6 * max(x1 - x0, y1 - y0))
            along_x = (x1 - x0) >= (y1 - y0)
            sx, sy = (Lb, 0.16) if along_x else (0.16, Lb)
            zb = ceil - 0.08                                      # hung 0.4 m: a flush panel at ceiling centre never entered a corner probe's
            # frame -- 'no ceiling lights in any back room' (floor G r30, 3 of 3)
            rods = [(cx_ + (sx / 2 - 0.1) * k if along_x else cx_, cy_ if along_x else cy_ + (sy / 2 - 0.1) * k, (zb + ceil) / 2, 0.01, 0.01, ceil - zb)
                    for k in (1, -1)]
            pa._parts_object(f"CeilingLightFactory(svc).spawn_asset(p{n_svc})", [(hous, [(cx_, cy_, zb + 0.04, sx + 0.02, sy + 0.02, 0.06)] + rods),
                                                                                 (led, [(cx_, cy_, zb, sx, sy, 0.02)])])
        if sum(e for q, e in lit if x0 <= q.x <= x1 and y0 <= q.y <= y1 and q.z > fz) >= 150.0:
            n_svc += 0 if fixture else 1
            continue                             # one 92 W lamp over a stall row left a restroom near black (floor H r5)
        add_point(f"svc{n_svc}", Vector(((x0 + x1) / 2, (y0 + y1) / 2, cz)), 40.0 * max(1.0, (x1 - x0) * (y1 - y0) / 6.0),
                  kelvin_rgb(4000), 0.3)
        n_svc += 1
    stats["service_lights"] = n_svc
    service_room_lights(stats, clinic=spec.get("venue") in ("clinic-reception", "exam-room", "dental-room", "physio-room"))
    street_backdrop(stats)
    if os.environ.get("ROOM_GLASS_PARTITIONS"):                   # glass door leaves + hallway EXIT signs (after flush_doors); see room_planner/glass_partitions.py
        from room_planner import glass_partitions
        glass_partitions.finish(stats)
    if os.environ.get("ROOM_ENV_WINDOWS") == "1":               # a real outside view behind every exterior window, not only ROOM_BIGGLASS ones (review 10-19)
        import env_windows
        env_windows.apply(stats)
    if os.environ.get("ROOM_FROSTED_WINDOW_ROOMS"):             # service rooms: a high narrow frosted window, not a big clear pane (floors G / H refs); see frosted_windows.py
        try:
            import frosted_windows
            frosted_windows.apply(stats)
        except Exception as ex:                                  # noqa: BLE001 -- a failed finishing pass must not fail the scene
            stats["frosted_windows_error"] = str(ex)[:100]
    if os.environ.get("ROOM_HUNG_LIGHTS"):                      # ceiling lights hung off the ceiling instead of flush (review 10-19)
        import hung_lights
        hung_lights.apply(stats)
    if os.environ.get("ROOM_FLOOR_TILE_ROOMS"):                   # pale porcelain tile in the listed room types (P2 kitchen / utility / balcony / baths); see tile_floor.py
        import tile_floor
        tile_floor.apply(stats)
    if os.environ.get("ROOM_DRUM_PENDANT") or os.environ.get("ROOM_LINEAR_PENDANT") or os.environ.get("ROOM_NO_ABO_FIXTURES"):       # a drum pendant over the sofa / a linear pendant over the dining table, placed directly; see lights_over.py
        import lights_over
        with provenance.gated("lights_over"):
            lights_over.apply(stats)
    if os.environ.get("ROOM_ABSTRACT_ART"):                       # paired square abstract prints instead of the random landscape pictures in the listed rooms; see abstract_art.py
        import abstract_art
        with provenance.gated("abstract_art", "wall_art"):
            abstract_art.apply(stats)
    if os.environ.get("ROOM_TRUSS_ROOMS"):                       # open steel trusses across the listed rooms; see hall_trusses.py
        import hall_trusses
        hall_trusses.apply(stats)
    if os.environ.get("ROOM_COVE_ROOMS"):                         # cove lighting (a dropped lip + a warm emissive strip) in the listed rooms; see cove_light.py
        import cove_light
        cove_light.apply(stats)
    if os.environ.get("ROOM_WALL_TILE_ROOMS"):                    # white square wall tile in the listed room types (floors G / H restroom); see tile_walls.py
        import tile_walls
        tile_walls.apply(stats)
    if os.environ.get("ROOM_FLOOR_CARPET"):                       # dark streaked carpet tiles (floor O ref); see carpet_floor.py
        import carpet_floor
        carpet_floor.apply(stats)
    if os.environ.get("ROOM_FLOOR_TERRAZZO") == "1":            # light terrazzo-speckled floor (S16 ref)
        import terrazzo_floor
        terrazzo_floor.apply(stats)
    if os.environ.get("ROOM_FLOOR_HERRINGBONE"):                  # herringbone plank floor, e.g. S13's pale lilac tile (ROOM_FLOOR_HERRINGBONE=0.78,0.68,0.78); see herringbone_floor.py
        import herringbone_floor
        herringbone_floor.apply(stats)
    if os.environ.get("ROOM_MODE"):                             # a mode's own ceiling (tools/infinigen/<mode>_ceiling.py: apply(stats)), if it has one
        try:
            import importlib
            importlib.import_module(os.environ["ROOM_MODE"] + "_ceiling").apply(stats)
        except ModuleNotFoundError:
            pass
    if os.environ.get("ROOM_BASEBOARD") == "1":                 # skirting boards round every room, not across doors / full-height glass (floor C r23 SRF-01)
        import baseboard
        baseboard.apply(stats)
    if os.environ.get("ROOM_FLOOR_SCUFF") == "1":               # dull patches + fine scratches on any floor material (S24: a mirror-like glossy floor)
        import floor_scuff
        floor_scuff.apply(stats)
    if os.environ.get("ROOM_COFFER_CEILING") == "1":            # plaster coffers + cornice (S10 r11: a flat dark brown ceiling)
        import plaster_ceiling
        plaster_ceiling.apply(stats)
    if os.environ.get("ROOM_LAB_CEILING") == "1":               # exposed beam / pipe service ceiling over the research corridor (floor N)
        import lab_ceiling
        lab_ceiling.apply(stats)
    # monitor shells in plain dark plastic: an Infinigen monitor variant rendered 'purple speckled, gemstone-like' (floor D3 r12, 3 of 3)
    # F3 r25 'monitor face shows vertical planks': proc_assets._flat gives every material whose name contains 'plastic' / 'monitor' a SCANNED plastic detail (texturecan_plastic_0005, 0.5 m tile): its ribs
    # showed on the casing and on any face whose slot was swapped for it. So: a casing name without those words, and the screen faces (the mesh's `screen` face attribute) always get the dark screen material.
    blk = pa._flat("ir_mon_casing", (0.035, 0.035, 0.04), 0.45)
    scr = pa._flat("ir_mon_screen_dark", (0.02, 0.03, 0.05), 0.15); _sb = scr.node_tree.nodes["Principled BSDF"]
    _sb.inputs["Emission Color"].default_value = (0.35, 0.5, 0.75, 1); _sb.inputs["Emission Strength"].default_value = 0.4
    n_mon = 0
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name.split("(")[0] in ("MonitorFactory", "TVFactory"):
            for sl in o.material_slots:
                if sl.material and not any(k in sl.material.name.lower() for k in ("screen", "display", "emission")):
                    sl.material = blk
            attr = o.data.attributes.get("screen")
            if attr is not None and attr.domain == "FACE":
                scr_m = scr
                if os.environ.get("ROOM_SCREEN_CONTENT") == "1":                    # A2 r19 CNT-02: the same blue dashboard on every monitor -> one of 10 synthetic screens (dashboards / code / documents / sheet / call / mail) per monitor
                    import glob
                    import zlib
                    imgs = sorted(glob.glob("/jarvis/project/robomituba/data/venue_refs/screen_content/screen_*.png"))
                    if imgs:
                        pth = imgs[zlib.crc32(o.name.encode()) % len(imgs)]; mn = f"ir_mon_content_{pth[-6:-4]}"
                        scr_m = bpy.data.materials.get(mn)
                        if scr_m is None:
                            scr_m = pa._flat(mn, (0.02, 0.02, 0.02), 0.2); bs = scr_m.node_tree.nodes["Principled BSDF"]
                            tx = scr_m.node_tree.nodes.new("ShaderNodeTexImage"); tx.image = bpy.data.images.load(pth, check_existing=True)
                            scr_m.node_tree.links.new(tx.outputs["Color"], bs.inputs["Emission Color"]); bs.inputs["Emission Strength"].default_value = 1.1
                o.data.materials.append(scr_m); si = len(o.data.materials) - 1
                for p_, v_ in zip(o.data.polygons, attr.data):
                    if v_.value:
                        p_.material_index = si
            n_mon += 1
    stats["monitors_matte"] = n_mon
    if os.environ.get("ROOM_FIX_MONITORS", "1") != "0":          # screens face the user (a monitor 176 deg off its chair on floor E3 r24; user 10-19: 'turned around or 90 deg')
        import fix_monitors
        fix_monitors.apply(stats)
    # no mood cap on daylight: tried 2026-10-16 (round J) -- chain stayed +16 L bright, industrial fell 50 -> 44 in the style eval
    bpy.context.scene["ir_daylight"] = (L or {}).get("daylight", "high")
    bpy.context.scene["ir_mood"] = spec.get("mood", "bright_daylight") if L else "bright_daylight"
    if bpy.context.scene["ir_mood"] == "dark_moody":              # evening outside a candle-lit room: the street was lit like noon (S10 r2: windows overexposed white)
        for m_ in bpy.data.materials:
            b_ = m_.node_tree.nodes.get("Principled BSDF") if m_.use_nodes and m_.name.startswith("ir_street_") else None
            if b_ is not None:
                c_ = b_.inputs["Base Color"].default_value; b_.inputs["Base Color"].default_value = (c_[0] * 0.25, c_[1] * 0.25, c_[2] * 0.3, 1.0)
    pass  # os is imported at module level (a local import made os unbound for the ENV/HUNG hooks above)
    import fix_print_uvs                                         # printed boards / screens / papers built before the UV fix (proc_assets._face_uvs)
    stats["print_uvs_fixed"] = fix_print_uvs.fix()
    if os.environ.get("ROOM_CLINIC_LOBBY") == "1" and a.plans:  # warm clinic lobby: plaster ceiling with a cove, 3 pendants, the office grid / tubes removed
        try:
            import clinic_lobby_ceiling
            stats["clinic_lobby_ceiling"] = clinic_lobby_ceiling.apply(json.loads(Path(a.plans).read_text()))
        except Exception as ex:                                  # noqa: BLE001 -- a failed ceiling must not fail the scene
            stats["clinic_lobby_ceiling_error"] = str(ex)[:100]
    if any(os.environ.get(k) for k in ("ROOM_BIGGLASS", "ROOM_FEATURE_WALL", "ROOM_TILE_WALL", "ROOM_SMOOTH_FLOOR", "ROOM_WHITE_CEILING", "ROOM_FLAT_WALLS", "ROOM_DENTAL_LIGHT", "ROOM_CEILING_RGB", "ROOM_CHANDELIER", "ROOM_PANEL_WALLS", "ROOM_RUGS", "ROOM_WALL_BAND", "ROOM_SPREAD_PLANTS", "ROOM_SLAT_BEHIND", "DOOR_FRAME_RGB", "DOOR_LEAF_RGB", "ROOM_OPEN_BLINDS", "ROOM_MARKET_CEILING")) and a.plans:   # post-realize: floating wall items in the glass opening, accent wall behind the exam table
        try:
            import late_walls
            stats["late_walls"] = late_walls.apply(json.loads(Path(a.plans).read_text()))
        except Exception as ex:                                  # noqa: BLE001 -- a failed finishing pass must not fail the scene
            stats["late_walls_error"] = str(ex)[:100]
    if os.environ.get("ROOM_OPEN_DOORS", "1") != "0":            # user 2026-10-18: doors between rooms and cubicle doors stand open
        try:
            import late_walls
            stats["open_doors"] = late_walls.open_doors()
        except Exception as ex:                                  # noqa: BLE001 -- a failed finishing pass must not fail the scene
            stats["open_doors_error"] = str(ex)[:100]
    if os.environ.get("ROOM_DOOR_BACKDROP") == "1":              # a corridor stub behind doors that open onto nothing (S17 r34: the empty world rendered as a pale panel in the doorway)
        try:
            import door_backdrop
            stats["door_backdrop"] = door_backdrop.apply()
        except Exception as ex:                                  # noqa: BLE001 -- a failed finishing pass must not fail the scene
            stats["door_backdrop_error"] = str(ex)[:100]
    cut = bpy.data.collections.get("placeholders:portal_cutters")     # Infinigen's door / window portal volumes are boolean cutters, not geometry: left visible they fill a doorway with a grey panel (S17 r31 LAY-01)
    if cut is not None and os.environ.get("ROOM_HIDE_PORTAL_CUTTERS", "1") != "0":
        for o in cut.all_objects:
            o.visible_camera = o.visible_diffuse = o.visible_glossy = o.visible_transmission = o.visible_volume_scatter = o.visible_shadow = False   # ray visibility, not hide_render: hiding it segfaulted the kit stage (S17 r32)
        stats["portal_cutters_hidden"] = len(cut.all_objects)
    try:                                                         # Infinigen's monocot leaf albedo is ~5 % (near black, backlit worse): lift x2.4 with a yellower light stop; ROOM_PLANT_LIFT=0 off
        import plant_leaf_lift
        stats["plant_leaf_lift"] = plant_leaf_lift.apply()
    except Exception as ex:                                      # noqa: BLE001 -- a failed finishing pass must not fail the scene
        stats["plant_leaf_lift_error"] = str(ex)[:100]
    if os.environ.get("IR_ARCH_TEX", "1") != "0":                # scanned texturecan walls / floors in place of Infinigen 2.0's flat `paint`
        import architecture_textures
        plans = json.loads(Path(a.plans).read_text())
        stats["archtex"] = architecture_textures.apply(plans.get("room_venues") or {}, (plans.get("style_spec") or {}).get("venue"), (plans.get("style_spec") or {}).get("floor"))
    if os.environ.get("IR_WEATHER", "1") != "0":                 # wear and grime on every material (user 2026-10-17: 'PBR parameters are flat
        import weather_pass                                      # constants', 'too smooth / too clean'); IR_WEATHER=0 keeps the flat look
        venue = (json.loads(Path(a.plans).read_text()).get("style_spec") or {}).get("venue") if a.plans else None
        # clean venues wear less: 1.0 was judged right for the café hall and stockroom, 'far too heavy' on the white office floor A2 r17
        # (user 2026-10-17); IR_WEATHER_STRENGTH still overrides
        base = {"office": 0.5, "open-office": 0.5, "meeting-room": 0.5, "clinic-reception": 0.45, "exam-room": 0.45, "dental-room": 0.45,
                "physio-room": 0.45, "pharmacy": 0.5, "boutique": 0.55, "convenience": 0.85, "grocery": 0.85}.get(venue, 1.0)
        stats["weathered"] = weather_pass.weather_materials(float(os.environ.get("IR_WEATHER_STRENGTH", base)))
    if os.environ.get("IR_WEATHER_VARIATION", "1") != "0":       # per-object offset/tint/edge wear after weather_pass: identical objects stopped being one
        try:                                                     # stamped copy (cafeP A/B arm 5, the only arm that moved things; user 'texture flat')
            import weather_variation
            stats["weather_variation"] = weather_variation.vary_materials(1.0, 0.35)
        except Exception as e:                                   # noqa: BLE001  -- never fail a scene over a finishing pass
            stats["weather_variation"] = f"failed: {e!r}"[:120]
    if os.environ.get("IR_PAINT_WEAR", "1") != "0":              # bare steel at edges/chips of painted metal: binary metallic mask
        try:
            import paint_wear
            stats["paint_wear"] = paint_wear.apply()
        except Exception as e:                                   # noqa: BLE001
            stats["paint_wear"] = f"failed: {e!r}"[:120]
    if os.environ.get("IR_GLAZE", "1") != "0":                   # glazed tiles at roughness ~1.0 in the GT channel -> capped at 0.28
        import glaze_fix
        stats["glaze_fixed"] = glaze_fix.fix(float(os.environ.get("IR_GLAZE_CAP", "0.28")))
    import displacement_fix                                      # brick/masonry relief: ~10x the physical depth reads at 512 px (cafeP_industrial A/B:
    stats["displacement_fixed"] = displacement_fix.fix(float(os.environ.get("IR_BUMP_SCALE", "10")))   # 1x flat, 4x faint, 12x clear, 30x noisy)
    if os.environ.get("ROOM_FLOOR_PATCHWORK") == "1":           # graphic black / red / white / mustard stepped tile patchwork (S34 LP cafe ref); see patchwork_floor.py. LAST: late_walls' ROOM_SMOOTH_FLOOR would replace it
        import patchwork_floor
        stats["patchwork_floor"] = patchwork_floor.apply(stats)
    if os.environ.get("ROOM_CHAIR_PLAIN") == "1":                # chairs: plain oak / walnut instead of Infinigen's blotchy shader groups (S31 r18); see chair_plain.py
        import chair_plain
        chair_plain.apply(stats)
    if os.environ.get("ROOM_CLEAR_GLASS") == "1":                # window glass blown out to white (S35 r14 / O4 r4); see clear_glass.py
        import clear_glass
        clear_glass.apply(stats)
    if os.environ.get("ROOM_LAB_FLOORMARKS") == "1" or os.environ.get("ROOM_LAB_BENCHDENSE") == "1" or os.environ.get("ROOM_LAB_PANEL_ROOMS") or os.environ.get("ROOM_MIRROR_CLEAR") == "1" or os.environ.get("ROOM_LAB_OPTICS") == "1" or os.environ.get("ROOM_WALL_DEDUPE") == "1":   # N2 (after late_walls' smooth floor, which would replace the mottle): bay tape + mottled floor, dense benches, panel ceiling (lab_extras.py)
        import lab_extras
        lab_extras.apply(stats)
    if os.environ.get("ROOM_TIMBER_CEILING") == "1":             # honey tongue-and-groove planks + dark log beams on the ceilings (S31 Stillroom); see timber_ceiling.py
        import timber_ceiling
        stats["timber_ceiling"] = timber_ceiling.apply(stats)
    if os.environ.get("ROOM_SCAN_WOOD") == "1":                 # scanned TextureCan woods on chairs / tables / counters / beams / floors by role; see scanned_wood.py (S31 / S32 realism, P1)
        import scanned_wood
        scanned_wood.apply(stats)
    if os.environ.get("ROOM_MAT_PASS") == "1" or os.environ.get("ROOM_HOME_SURF") == "1":                  # global material pass: calmer stucco blotch, floor macro roughness (realism program P1); see mat_pass.py
        import mat_pass
        mat_pass.apply(stats)
    if os.environ.get("ROOM_PLANT_FIX") == "1":                 # HSSD plant materials rebuilt fresh (O2 r24 white palms); see plant_fix.py
        import plant_fix
        plant_fix.apply(stats)
    if os.environ.get("ROOM_BATH_VEIN"):                        # greige veined satin stone + cove / mirror LEDs in bathrooms (H3 reference); see bath_stone.py
        import bath_stone
        bath_stone.apply(stats)
    if os.environ.get("ROOM_TERRACE_DRESS") == "1":             # slat wall + soffit downlights on the balcony (P2b); see terrace_dress.py
        import terrace_dress
        terrace_dress.apply(stats)
    if os.environ.get("ROOM_PLANTER_PEBBLES") == "1":           # white / black river-stone mulch on the atrium planters (O2); see planter_pebbles.py
        import planter_pebbles
        planter_pebbles.apply(stats)
    if os.environ.get("ROOM_PARKING_FIXTURES") == "1":          # car-park fixtures: hazard columns, fire cabinets, trays, jet fans, drain, stains, plugged windows, lobby drop ceiling; see parking_fixtures.py
        import parking_fixtures
        parking_fixtures.apply(stats)
    if os.environ.get("ROOM_PARKING_LOBBY") == "1":             # S28F pedestrian spaces: flush window plugs, tiled lift lobby with signs / dado / bench, lift surrounds, concrete stair, ramp height bar; see parking_lobby.py
        import parking_lobby
        parking_lobby.apply(stats)
    if any(os.environ.get(k) == "1" for k in ("ROOM_CEILING_CLEAN", "ROOM_WALL_VENEER", "ROOM_PIERS", "ROOM_WINDOW_SHELF", "ROOM_OFFICE_VENEER")):   # S35 strict bakery shell; see bakery_shell.py
        import bakery_shell
        bakery_shell.apply(stats)
    if any(os.environ.get(k_) == "1" for k_ in ("ROOM_ATRIUM_CEIL", "ROOM_ATRIUM_CLAD", "ROOM_ATRIUM_NICHES", "ROOM_ATRIUM_WEST")):   # S36 r6 atrium shell; see atrium_shell.py
        import atrium_shell
        atrium_shell.apply(stats)
    if os.environ.get("ROOM_LIGHT_TUNE") == "1":                # world / sun fill scaling, ceiling points -> down spots (S35 'light wrapping the soffits'); see light_tune.py
        import light_tune
        light_tune.apply(stats)
    if os.environ.get("ROOM_BOOK_FLAT") == "1":                 # kit-stage rerun of the book-on-bed check (P2b r34); realize runs it too
        from room_planner import support_check as _sc
        _sc.books(stats)
    if os.environ.get("ROOM_GEO_PASS") == "1" or os.environ.get("ROOM_GEO_SOFT") == "1":                  # global bevel + smooth ducts on procedural props (realism program P2); see geo_pass.py
        import geo_pass
        geo_pass.apply(stats)
    if os.environ.get("ROOM_EXPOSED_CEILING") == "1":           # raw concrete slab + beams + bare steel services (O3 urban-dirty; painted variant via ROOM_EXPOSED_CEILING_RGB); see exposed_ceiling.py
        import exposed_ceiling
        stats["exposed_ceiling"] = exposed_ceiling.apply(stats)
    if os.environ.get("ROOM_CONV_CEIL") == "1" or os.environ.get("ROOM_CONV_SLATS") == "1" or os.environ.get("ROOM_CONV_NOCOL") == "1" or os.environ.get("ROOM_CONV_FLOOR") or os.environ.get("ROOM_CONV_NOSIGNS") == "1" or os.environ.get("ROOM_PEG_LIB") == "1":     # S37 convenience shell: linear LED ceiling + AC cassette, walnut slat walls, no columns; see conv_shell.py
        import conv_shell
        conv_shell.apply(stats)
    if os.environ.get("ROOM_SHOPFRONT_FIX") == "1":           # shop front (S38 r15 / S37): glass swing door, paved street + kerb + planters, glass-office window plate; see shopfront_fix.py
        import shopfront_fix
        shopfront_fix.apply(stats)
    if os.environ.get("ROOM_LIQ_SHELL") == "1":                 # S38 wine shop: black track ceiling, wine wall + vineyard panels, brick gift wall, walnut cooler fascia, counter under-glow; see liq_shell.py
        import liq_shell
        liq_shell.apply(stats)
    if os.environ.get("ROOM_LUX_SHELL") == "1":                 # L1 lux showroom floor: hammered-steel ceiling + bronze U ribbons, LED wall, carpet / oak gallery, dark VIP lounge, warm downlights; see lux_shell.py
        import lux_shell
        lux_shell.apply(stats)
    if os.environ.get("ROOM_H2_REF") == "1":                    # H2 hotel floor reference gaps: dressed beds, pale broadloom, windows + curtains, oak furniture, corridor end windows / prints / downlights, stone baths; see h2_ref.py
        import h2_ref
        h2_ref.apply(stats)
    if os.environ.get("ROOM_BRICK_SHELL") == "1":               # S39 brick-loft restaurant: N + E steel glazing + sheers, brick, terrazzo, dome / Edison pendants, mahogany + olive furniture, tufted banquette, wine cooler; see brick_shell.py
        import brick_shell
        brick_shell.apply(stats)
    if os.environ.get("ROOM_APT_SHELL") == "1":                 # P7-P9 apartment floors: oak floors, per-unit walls, warm lights, wardrobes, baths, dining sets; see apt_shell.py
        import apt_shell
        apt_shell.apply(stats)
    if os.environ.get("ROOM_BOOKHALL_SHELL") == "1":            # B3 bookHall_01 large high-ceilinged bookstore hall: lattice ceiling, towers, gondolas, mezzanine, parquet; see bookhall_shell.py
        import bookhall_shell
        bookhall_shell.apply(stats)
    if os.environ.get("ROOM_HOTEL5_SHELL") == "1":              # H5 hotel floor: sky lounge, lift hall, corridor, guest rooms, banquet lobby / hall; see hotel5_shell.py
        import hotel5_shell
        hotel5_shell.apply(stats)
    if os.environ.get("ROOM_CONVFLOOR_SHELL") == "1":           # F1 convention floor: inlaid marble, stone + fluted walnut walls, chandeliers, poster niches, stages, reception, lift bank; see convfloor_shell.py
        import convfloor_shell
        convfloor_shell.apply(stats)
    if os.environ.get("ROOM_PERF_CEILING"):                     # 600x600 perforated metal tile ceiling on the listed ceiling prefixes (O2 hallway); see perf_ceiling.py
        import perf_ceiling
        perf_ceiling.apply(stats)
    if os.environ.get("ROOM_RAMEN_DRESSING") == "1":            # ramen counter shop: recessed warm downlights + a cool hood light instead of the domestic round fixtures, and menu boards / hooks / notices on the wall opposite the kitchen; see ramen_dressing.py
        import ramen_dressing
        stats["ramen_dressing"] = ramen_dressing.apply(stats)
    if os.environ.get("ROOM_RAMEN_UTENSILS") == "1":            # ladles / tongs / tebo baskets, library spoons, stock pots with lids, a bowl tray, a board + knife on the ramen line; see ramen_utensils.py
        import ramen_utensils
        stats["ramen_utensils"] = ramen_utensils.apply(stats)
    if os.environ.get("ROOM_WALL_DRESSING") == "1":             # framed prints, whiteboards, pin boards, felt panels, shelves on the free wall runs of offices / lounges / meeting rooms; see wall_dressing.py
        import wall_dressing
        stats["wall_dressing"] = wall_dressing.apply(stats)
    if os.environ.get("ROOM_FLOOR_CHECKER"):                    # black / white checker tiles on the listed floors (O5 cafe); see checker_floor.py
        import checker_floor
        stats["checker_floor"] = checker_floor.apply(stats)
    if os.environ.get("ROOM_FLOOR_STRIPES") == "1":             # chevron colour bands on the listed floors (O5 creative office); see floor_stripes.py
        import floor_stripes
        stats["floor_stripes"] = floor_stripes.apply(stats)
    if os.environ.get("ROOM_SURFACE_REALISM") == "1":           # roughness range per material class + 3-scale variation + micro normal + shader bevel, per-tile variation, glossy black, window daylight (user 10-23 S32 vs S34); see surface_realism.py. After every pass that creates materials
        import surface_realism
        stats["surface_realism"] = surface_realism.apply(stats)
    if os.environ.get("ROOM_MFG_DETAIL") == "1":                # axis B manufacturing details: bevels, switch plates + sockets, door hinges, ceiling vents (user 10-23); see mfg_detail.py
        import mfg_detail
        stats["mfg_detail"] = mfg_detail.apply(stats)
    if os.environ.get("ROOM_USAGE_REAL") == "1":                # axis C usage realism: chairs/stools turned and slid, per-object colour jitter inside repeats; see usage_realism.py
        import usage_realism
        stats["usage_realism"] = usage_realism.apply(stats)
    import fixture_tags                                         # ir_fixture = the fixture mesh each light belongs to ("" if none), for the opticalnav simulator; see fixture_tags.py
    stats["fixture_tags"] = fixture_tags.apply(stats)
    for _k in set(bpy.data.objects.keys()) - _kit_before:        # what the kit stage added and no pass above tagged (architecture, openings, ceilings, lights ...)
        _o = bpy.data.objects.get(_k)
        if _o is not None and "src" not in _o:
            _o["src"] = "arch:kit_stage"
    try:                                                         # O2-DOOR-3: door plugs follow the wall material the later passes gave the wall (late_walls.sync_plugs)
        import late_walls
        stats["door_plugs_synced"] = late_walls.sync_plugs()
    except Exception as ex:                                      # noqa: BLE001
        stats["door_plugs_error"] = str(ex)[:100]
    provenance.write(a.out, stats)
    bpy.ops.wm.save_as_mainfile(filepath=a.out, compress=True)
    print("KITLIGHT " + json.dumps(stats), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
