"""Architectural envelope for a commercial room (user 2026-10-16: the cafes read as "an empty box with cafe objects in it").

Runs in Blender on the rematerialled blend, BEFORE the room plan, so the planner sees the structure as existing objects and furnishes
around it:

  pilasters    0.3-0.45 m piers on long walls every 3-4 m (and a free-standing column in rooms over 60 m2)
  beams        down-stand beams across the short span, aligned with the pilasters
  soffit       a dropped bulkhead (0.35 m) along the back wall: where a counter sits in a real shop
  accent wall  one long wall gets the palette's accent material (a second material slot on the wall mesh, faces by plane)
  ceiling kit  a duct run along the room, a pipe pair, track rails with spot heads (+ narrow spot lights), an AC cassette, sprinkler
               heads -- the medium-frequency detail that gives a ceiling its depth and scale

    python architecture_pass.py IN.blend --out OUT.blend --seed N [--palette spec.json]   (infinigen env, bpy as a module)

Every object is named <Kind>Factory(seed).spawn_asset(i) like the rest, so extract_rooms / obstacles / the board see them. Ceiling
objects hang above 2.3 m and are listed as HANGING (no floor footprint).
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import furnish_rooms as fr  # noqa: E402
import room_dressing as rd  # noqa: E402
from room_planner import proc_assets as pa  # noqa: E402

#: per-element odds by archetype (user 2026-10-16: one fixed kit made every cafe the same shell; thick columns read as a car park)
ARCHETYPES = {
    "modern":     dict(pilaster=.6, beam=.5, column=.5, soffit=.7, duct=.2, pipe=.15, track=.8, ac=.6, sprinkler=.8),
    "apartment":  dict(pilaster=0, beam=0, column=0, soffit=0, duct=0, pipe=0, track=0, ac=0, sprinkler=0),   # homes (P2b r3: 'no ceiling beams in apartments'): a smooth ceiling, no exposed services
    "minimal":    dict(pilaster=0, beam=0, column=0, soffit=0, duct=0, pipe=0, track=.8, ac=.6, sprinkler=.8),   # S8 minimal bar: no beams/columns/soffit (reviewers: awkward ceiling structure)
    "truss_hall":  dict(pilaster=.3, beam=0, column=.4, soffit=0, duct=1.0, pipe=.6, track=.7, ac=.3, sprinkler=.7),   # H hall: ducts / pipes / columns but NO solid down-stand beams (open trusses come from hall_trusses.py)
    "industrial": dict(pilaster=.7, beam=.8, column=.6, soffit=.4, duct=.8, pipe=.7, track=.7, ac=.3, sprinkler=.8),
    "warm":       dict(pilaster=.4, beam=.3, column=.3, soffit=.6, duct=.05, pipe=.05, track=.4, ac=.4, sprinkler=.6),
    "bakery":     dict(pilaster=.3, beam=.2, column=.2, soffit=.8, duct=.1, pipe=.05, track=.5, ac=.5, sprinkler=.7),
    "office":     dict(pilaster=0, beam=0, column=.3, soffit=0, duct=0, pipe=0, track=0, ac=.3, sprinkler=.9, grid=1),
    "office_exposed": dict(pilaster=0, beam=.7, column=.4, soffit=0, duct=.6, pipe=.3, track=0, ac=1, sprinkler=.9, grid=0, linear=1),
    "exposed_flagship": dict(pilaster=0, beam=0, column=.5, soffit=0, duct=0, pipe=0, track=0, ac=0, sprinkler=.6, flagship=1),   # big boutique: room_planner/flagship_ceiling.py
    "bookstore": dict(pilaster=0, beam=0, column=.6, soffit=0, duct=0, pipe=0, track=0, ac=.3, sprinkler=.9, bookstore=1),   # room_planner/bookstore_ceiling.py
    "rooftop": dict(pilaster=0, beam=0, column=.5, soffit=0, duct=0, pipe=0, track=0, ac=0, sprinkler=0, rooftop=1),   # room_planner/rooftop_shell.py
    "winepub": dict(pilaster=0, beam=0, column=0, soffit=0, duct=0, pipe=0, track=0, ac=0, sprinkler=0, winepub=1),   # room_planner/winepub_ceiling.py
    "museum": dict(pilaster=0, beam=0, column=0, soffit=0, duct=0, pipe=0, track=0, ac=0, sprinkler=0, museum=1),   # room_planner/museum_shell.py (octagonal domed rotunda)
    "warehouse":  dict(pilaster=.3, beam=0, column=.5, soffit=0, duct=.4, pipe=.8, track=0, ac=0, sprinkler=1, warehouse=1),
    "default":    dict(pilaster=.6, beam=.6, column=.6, soffit=.6, duct=.35, pipe=.3, track=.7, ac=.45, sprinkler=.8),
}

PALETTE_DEFAULT = {"frame": (0.03, 0.03, 0.03), "structure": (0.82, 0.81, 0.78), "duct": (0.62, 0.62, 0.64),
                   "accent": (0.16, 0.17, 0.18)}


def _mat(name, rgb, rough=0.6, metallic=0.0):
    return pa._flat(name, tuple(rgb), rough, metallic)


def _box(name, parts, mat):
    return pa._parts_object(name, [(mat, parts)])


def _cyl(name, p0, p1, r, mat, n=12):
    import bmesh
    v = Vector(p1) - Vector(p0)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=n, radius1=r, radius2=r, depth=v.length)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free(); me.materials.append(mat)
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    o.location = (Vector(p0) + Vector(p1)) / 2
    o.rotation_mode = "QUATERNION"; o.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(v.normalized())
    return o


def office_ceiling(L, S, zc, at, name, rng, stats):
    """Drop-ceiling grid (0.6 m T-bars), linear LED rows every ~2.4 m with an area light each, HVAC diffusers, smoke detectors: the
    repeated ceiling rhythm that reads 'office' in perspective (user 2026-10-16)."""
    tbar = _mat("ir_tbar", (0.62, 0.62, 0.62), 0.4, 0.5)   # darker than the tiles so the grid reads at eye level (critic r1)
    grid = [(at(u, S / 2)[0], at(u, S / 2)[1], zc - 0.01, 0.03, S, 0.02) for u in [k * 0.6 for k in range(1, int(L / 0.6))]]
    grid += [(at(L / 2, v)[0], at(L / 2, v)[1], zc - 0.01, L, 0.03, 0.02) for v in [k * 0.6 for k in range(1, int(S / 0.6))]]
    _box(name("CeilingGrid"), grid, tbar)
    led = pa._flat("ir_led_panel", (1.0, 1.0, 1.0), 0.3)
    nt = led.node_tree; b = nt.nodes["Principled BSDF"]
    b.inputs["Emission Color"].default_value = (1.0, 0.97, 0.92, 1); b.inputs["Emission Strength"].default_value = 4.0
    led_k = float(__import__("os").environ.get("CEILING_LED_SCALE", "1.0"))                  # >1 spaces the LED panels further apart (S20: the panels repeat too much)
    rows = max(1, int(S / (2.4 * led_k)))
    for r_ in range(rows):
        v = S * (r_ + 0.5) / rows
        n = max(1, int((L - 0.6) / (1.8 * led_k)))
        for k in range(n):
            u = 0.6 + (k + 0.5) * (L - 1.2) / n
            cx, cy = at(u, v)
            _box(name("LinearLed"), [(cx, cy, zc - 0.02, 1.2, 0.3, 0.03)], led)   # a 1200x300 troffer panel
            ld = bpy.data.lights.new(f"ir_led_{r_}_{k}", "AREA"); ld.shape = "RECTANGLE"; ld.size = 1.2; ld.size_y = 0.3; ld.energy = 45.0 * float(__import__("os").environ.get("CEILING_LED_POWER", "1.0"))   # env CEILING_LED_POWER: softer light (S20: 0.65)
            lo = bpy.data.objects.new(f"PointLampFactory(led).spawn_asset({r_}_{k})", ld)
            bpy.context.scene.collection.objects.link(lo); lo.location = (cx, cy, zc - 0.05)
            stats["linear_leds"] = stats.get("linear_leds", 0) + 1
    diff = _mat("ir_diffuser", (0.78, 0.78, 0.77), 0.5, 0.2)
    for k in range(max(1, int(L / 3.0))):
        cx, cy = at(1.5 + k * 3.0, S * (0.25 if k % 2 else 0.75))
        _box(name("Diffuser"), [(cx, cy, zc - 0.015, 0.6, 0.6, 0.02), (cx, cy, zc - 0.03, 0.4, 0.4, 0.02)], diff)
        cx, cy = at(1.5 + k * 3.0, S * 0.5)
        _cyl(name("SmokeDetector"), (cx, cy, zc - 0.005), (cx, cy, zc - 0.04), 0.06, _mat("ir_ac_white", (0.86, 0.86, 0.85), 0.4), n=16)


def linear_pendants(L, S, zc, at, name, rng, stats):
    """Exposed-ceiling office: slim linear LED pendants on two rods at ~2.55 m in rows, an AC cassette every ~4 m (reference photo
    2026-10-16)."""
    body = _mat("ir_linear_body", (0.06, 0.06, 0.06), 0.4, 1.0)
    led = pa._flat("ir_led_panel", (1.0, 1.0, 1.0), 0.3)
    led.node_tree.nodes["Principled BSDF"].inputs["Emission Color"].default_value = (1.0, 0.97, 0.92, 1)
    led.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = 4.0
    rows = max(1, int(S / 2.2)); z = min(zc - 0.4, 2.6)
    for r_ in range(rows):
        v = S * (r_ + 0.5) / rows
        n = max(1, int((L - 0.8) / 2.0))
        for k in range(n):
            u = 0.4 + (k + 0.5) * (L - 0.8) / n
            cx, cy = at(u, v)
            _box(name("LinearPendant"), [(cx, cy, z, 1.5, 0.06, 0.06), (cx - 0.65, cy, (z + zc) / 2, 0.006, 0.006, zc - z),
                                          (cx + 0.65, cy, (z + zc) / 2, 0.006, 0.006, zc - z)], body)
            _box(name("LinearLed"), [(cx, cy, z - 0.031, 1.46, 0.045, 0.004)], led)
            ld = bpy.data.lights.new(f"ir_lin_{r_}_{k}", "AREA"); ld.shape = "RECTANGLE"; ld.size = 1.45; ld.size_y = 0.05; ld.energy = 50.0
            lo = bpy.data.objects.new(f"PointLampFactory(linear).spawn_asset({r_}_{k})", ld)
            bpy.context.scene.collection.objects.link(lo); lo.location = (cx, cy, z - 0.04)
            stats["linear_pendants"] = stats.get("linear_pendants", 0) + 1
    ac = _mat("ir_ac_white", (0.86, 0.86, 0.85), 0.4)
    for k in range(max(1, int(L / 4.0))):
        cx, cy = at(2.0 + k * 4.0, S * (0.3 if k % 2 else 0.7))
        _box(name("AcCassette"), [(cx, cy, zc - 0.04, 0.84, 0.84, 0.06), (cx, cy, zc - 0.09, 0.62, 0.62, 0.04)], ac)


def warehouse_roof(L, S, zc, at, name, rng, stats):
    """Industrial roof (warehouse r1 critic: 'a flat white plaster ceiling with dome/pendant lights reads as a basement'): a
    corrugated deck of ribs, steel girders every ~4.5 m with purlins, and high-bay dome lights on cords in rows over the aisles.
    Infinigen's ceiling pucks in the room are removed, so the fixture pass does not hang household lamps here."""
    _wsr = __import__("os").environ.get("WAREHOUSE_STEEL_RGB")                                  # env "r,g,b" (linear): pale grey girders instead of the random blue (floor J ref: white/grey hall)
    steel = _mat("ir_wh_steel", tuple(float(x) for x in _wsr.split(",")) if _wsr else rng.choice(((0.32, 0.36, 0.42), (0.55, 0.56, 0.58), (0.12, 0.2, 0.36))), 0.5, 0.6)
    deck = _mat("ir_wh_deck", (0.62, 0.63, 0.64), 0.45, 0.8)
    alu = _mat("ir_wh_alu", (0.8, 0.8, 0.82), 0.3, 1.0)
    glow = pa._flat("ir_highbay_glow", (1.0, 1.0, 1.0), 0.3)
    glow.node_tree.nodes["Principled BSDF"].inputs["Emission Color"].default_value = (1.0, 0.97, 0.92, 1)
    glow.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = 12.0
    ribs = [(*at(L / 2, S / 2), zc - 0.004, L, S, 0.008)]      # the deck sheet hides the plaster; ribs give it the corrugation
    ribs += [(*at(0.15 + k * 0.3, S / 2), zc - 0.035, 0.1, S, 0.06) for k in range(int(L / 0.3))]
    _box(name("RoofDeck"), ribs, deck)
    gird = []
    n_g = max(1, round(L / 4.5))
    for k in range(1, n_g):
        cx, cy = at(L * k / n_g, S / 2)
        gird += [(cx, cy, zc - 0.08, 0.2, S, 0.02), (cx, cy, zc - 0.5, 0.2, S, 0.02), (cx, cy, zc - 0.29, 0.015, S, 0.42)]
    for v in [0.6 + k * 1.2 for k in range(int((S - 0.6) / 1.2))]:
        cx, cy = at(L / 2, v)
        gird.append((cx, cy, zc - 0.14, L, 0.08, 0.15))
    _box(name("RoofGirder"), gird, steel)
    rows = max(2, round(S / 4.0)); per = max(2, round(L / 4.0)); zh = zc - rng.uniform(0.9, 1.3)
    for r_ in range(rows):
        for k in range(per):
            cx, cy = at(L * (k + 0.5) / per, S * (r_ + 0.5) / rows)
            # linear strip fixtures on chains along the aisles (wh r16: dome high-bays seen from below read as flat residential discs)
            for dx in (-0.6, 0.6):
                _cyl(name("HighBayCord"), (cx + dx, cy, zc - 0.05), (cx + dx, cy, zh + 0.04), 0.006, steel, n=6)
            o = pa._prims(name("HighBayLamp"), [(alu, [("box", (cx, cy, zh), (1.5, 0.16, 0.08), (0, 0, 0)),
                                                       ("box", (cx, cy + 0.07, zh - 0.05), (1.5, 0.02, 0.06), (0, 0, 0)),
                                                       ("box", (cx, cy - 0.07, zh - 0.05), (1.5, 0.02, 0.06), (0, 0, 0))]),
                                                (glow, [("box", (cx, cy, zh - 0.045), (1.44, 0.12, 0.01), (0, 0, 0))])])
            ld = bpy.data.lights.new(f"ir_highbay_{r_}_{k}", "POINT"); ld.energy = 350.0; ld.color = (1.0, 0.97, 0.92); ld.shadow_soft_size = 0.2
            lo = bpy.data.objects.new(f"PointLampFactory(highbay).spawn_asset({r_}_{k})", ld)
            bpy.context.scene.collection.objects.link(lo); lo.location = (cx, cy, zh - 0.3)
            stats["highbay"] = stats.get("highbay", 0) + 1
    x0, x1 = min(at(0, 0)[0], at(L, S)[0]), max(at(0, 0)[0], at(L, S)[0])
    y0, y1 = min(at(0, 0)[1], at(L, S)[1]), max(at(0, 0)[1], at(L, S)[1])
    for o in [o for o in bpy.data.objects if rd._factory(o.name) == "CeilingLightFactory"]:
        t = o.matrix_world.translation
        if x0 <= t.x <= x1 and y0 <= t.y <= y1:
            for c in list(o.children_recursive):
                bpy.data.objects.remove(c, do_unlink=True)
            bpy.data.objects.remove(o, do_unlink=True)
            stats["pucks_removed"] = stats.get("pucks_removed", 0) + 1


def room_frame(room):
    """(x0, x1, y0, y1, floor z, ceiling z) of a roughly rectangular room, from its floor and wall meshes."""
    x0, x1, y0, y1 = room.box
    ceil = max((room.wall.matrix_world @ Vector(c)).z for c in room.wall.bound_box)
    return x0, x1, y0, y1, room.z, ceil


def accent_wall(room, mat, rng, stats):
    """Second material on the faces of one long wall (the one opposite the door if known, else random of the two)."""
    me, mw = room.wall.data, room.wall.matrix_world
    x0, x1, y0, y1 = room.box
    axis, at_ = rng.choice((("y", y1), ("y", y1), ("x", x0), ("x", x1)))   # back wall (behind the counter) or a side wall; never the glass
    if mat.name not in [m.name for m in me.materials if m]:
        me.materials.append(mat)
    slot = [m.name if m else "" for m in me.materials].index(mat.name)
    hit = 0
    for p in me.polygons:
        c = mw @ p.center; n = (mw.to_3x3() @ p.normal).normalized()
        if abs(n.z) > 0.3:
            continue
        if (abs(c.y - at_) < 0.25 and abs(n.y) > 0.8) if axis == "y" else (abs(c.x - at_) < 0.25 and abs(n.x) > 0.8):
            p.material_index = slot; hit += 1
    stats["accent_faces"] = stats.get("accent_faces", 0) + hit
    return axis, round(at_, 2)


def build(room, rng, pal, stats, seed, track=True, archetype="default"):
    odds = ARCHETYPES.get(archetype, ARCHETYPES["default"])
    has = {k: rng.random() < p for k, p in odds.items()}
    has["track"] = has["track"] and track
    if str(getattr(room, "name", "")).split("_")[0] in ("restroom", "utility", "closet", "bathroom"):   # a service room keeps a plain
        for k in ("duct", "pipe", "track", "beam", "column", "pilaster", "soffit", "linear"):   # ceiling: 'a low diagonal duct and track spots
            has[k] = False                                                             # in a customer WC' (floor H r12-r14, 3 of 3)
    stats["archetype"], stats["elements"] = archetype, sorted(k for k, v in has.items() if v)
    x0, x1, y0, y1, z0, zc = room_frame(room)
    W, D = x1 - x0, y1 - y0
    long_x = True                                               # u = x, v = y: the storefront is the y0 wall, the back wall y1
    L, S = W, D
    struct = _mat("ir_arch_structure", pal["structure"], 0.85)
    frame = _mat("ir_arch_black_metal", pal["frame"], 0.4, 1.0)
    duct = _mat("ir_arch_duct", pal["duct"], 0.35, 1.0)
    i = [0]

    def name(kind):
        i[0] += 1
        return f"{kind}Factory({seed}).spawn_asset({i[0]})"

    def at(u, v):                                               # u along the long axis, v across (room frame -> world)
        return (x0 + u, y0 + v) if long_x else (x0 + v, y0 + u)

    # pilasters + beams every 3-4 m along the long walls
    bays = max(1, round(L / rng.uniform(3.0, 4.0)))
    pw = rng.uniform(0.25, 0.35)
    beam_h = rng.uniform(0.3, 0.45)
    for k in range(1, bays if (has["pilaster"] or has["beam"]) else 1):
        u = L * k / bays
        for v in ((pw / 2, S - pw / 2) if has["pilaster"] else ()):
            cx, cy = at(u, v)
            _box(name("Pilaster"), [(cx, cy, (z0 + zc) / 2, pw, pw, zc - z0)], struct)
            stats["pilasters"] = stats.get("pilasters", 0) + 1
        if has["beam"]:
            cx, cy = at(u, S / 2)
            sx, sy = (0.3, S) if long_x else (S, 0.3)
            _box(name("CeilingBeam"), [(cx, cy, zc - beam_h / 2, sx, sy, beam_h)], struct)
            stats["beams"] = stats.get("beams", 0) + 1
    if W * D > 60 and bays >= 2 and has["column"]:                                # a free-standing column mid-room
        cx, cy = at(L / bays, S / 2)
        _box(name("Column"), [(cx, cy, (z0 + zc) / 2, 0.35, 0.35, zc - z0)], struct)
        stats["columns"] = 1
    # soffit along the back wall (v = S: the wall opposite the storefront at v = 0)
    sh = 0.35; sd = rng.uniform(0.9, 1.4)
    if has["soffit"]:
        cx, cy = at(L / 2, S - sd / 2)
        sx, sy = (L, sd) if long_x else (sd, L)
        _box(name("Soffit"), [(cx, cy, zc - sh / 2, sx, sy, sh)], struct)
    # ceiling kit: a duct run, a pipe pair, two track rails with spot heads, an AC cassette, sprinklers
    zd = zc - 0.3                                               # tight under the ceiling (café L: 'a duct at eye level cuts the frame')
    vduct = S * rng.uniform(0.3, 0.45)
    a, b = at(0.2, vduct), at(L - 0.2, vduct)
    if has["duct"]:
        _cyl(name("Duct"), (*a, zd), (*b, zd), rng.uniform(0.15, 0.22), duct, n=24)
    for dv in ((0.35, 0.45) if has["pipe"] else ()):
        a, b = at(0.1, vduct + dv), at(L - 0.1, vduct + dv)
        _cyl(name("Pipe"), (*a, zc - 0.12), (*b, zc - 0.12), 0.025, frame)
    spot_w = 12.0
    for vt in ((S * 0.62, S * 0.8) if has["track"] else ()):
        a, b = at(0.6, vt), at(L - 0.6, vt)
        _cyl(name("TrackRail"), (*a, zc - 0.05), (*b, zc - 0.05), 0.018, frame, n=8)
        n_spot = max(3, int((L - 1.2) / 1.1))
        for k in range(n_spot):
            u = 0.6 + (k + 0.5) * (L - 1.2) / n_spot
            cx, cy = at(u, vt)
            _cyl(name("TrackSpot"), (cx, cy, zc - 0.07), (cx, cy, zc - 0.22), 0.04, frame, n=12)
            ld = bpy.data.lights.new(f"ir_track_spot_{k}", "SPOT"); ld.energy = spot_w; ld.spot_size = math.radians(35)
            ld.spot_blend = 0.4; ld.shadow_soft_size = 0.03
            lo = bpy.data.objects.new(f"PointLampFactory(track).spawn_asset({i[0]}_{k})", ld)
            bpy.context.scene.collection.objects.link(lo)
            lo.location = (cx, cy, zc - 0.24)
            lo.rotation_euler = (math.radians(rng.uniform(15, 30)), 0, rng.uniform(0, 2 * math.pi))
            stats["track_spots"] = stats.get("track_spots", 0) + 1
    if has.get("grid"):
        office_ceiling(L, S, zc, at, name, rng, stats)
    if has.get("linear"):
        linear_pendants(L, S, zc, at, name, rng, stats)
    if has.get("warehouse"):
        warehouse_roof(L, S, zc, at, name, rng, stats)
    if has.get("flagship"):
        from room_planner import flagship_ceiling
        flagship_ceiling.flagship_services(L, S, zc, at, name, rng, stats)
    if has.get("bookstore"):
        from room_planner import bookstore_ceiling
        bookstore_ceiling.bookstore_services(L, S, zc, at, name, rng, stats)
    if has.get("museum"):
        from room_planner import museum_shell
        museum_shell.shell_services(L, S, zc, at, name, rng, stats, room=getattr(room, "name", None))
    if has.get("winepub"):
        from room_planner import winepub_ceiling
        winepub_ceiling.winepub_services(L, S, zc, at, name, rng, stats)
    if has.get("rooftop"):
        from room_planner import rooftop_shell
        rooftop_shell.shell_services(L, S, zc, zc + 1.8, at, name, rng, stats, room=getattr(room, "name", None))
    if __import__("os").environ.get("ROOM_BIGGLASS") in ("street", "skyline", "garden", "street_night"):         # floor-to-ceiling glass wall + exterior card + sun (room_planner/big_glass.py)
        from room_planner import big_glass
        big_glass.apply(L, S, zc, at, name, rng, stats, room=getattr(room, "name", None))
    if __import__("os").environ.get("ROOM_GLASS_PARTITIONS") and getattr(room, "name", None):          # glass walls between the listed room types and their neighbours (room_planner/glass_partitions.py)
        from room_planner import glass_partitions
        glass_partitions.apply(room.name, zc, stats)
    if __import__("os").environ.get("ROOM_TERRACE_OPEN") == "1" and getattr(room, "name", None):          # open terrace (glass railing) + floor-to-ceiling glazing of listed rooms (room_planner/terrace_open.py)
        from room_planner import terrace_open
        terrace_open.apply(room.name, zc, stats, rng)
    cx, cy = at(L * rng.uniform(0.6, 0.8), S * 0.2)
    if has["ac"]:
        _box(name("AcCassette"), [(cx, cy, zc - 0.04, 0.84, 0.84, 0.06), (cx, cy, zc - 0.09, 0.62, 0.62, 0.04)],
         _mat("ir_ac_white", (0.86, 0.86, 0.85), 0.4))
    for k in (range(max(2, int(L / 2.5))) if has["sprinkler"] else ()):
        cx, cy = at(1.2 + k * 2.5, S * 0.5 + (0.6 if k % 2 else -0.6))
        _cyl(name("Sprinkler"), (cx, cy, zc - 0.005), (cx, cy, zc - 0.06), 0.012, duct, n=8)


def exterior(hdr: str, rng, stats):
    """The world sees a city, not an empty gradient: an equirect HDRI into the world BACKGROUND colour. The renderer's lighting
    variants rename that node IR_Sky and set its strength; a linked colour input keeps the image."""
    world = bpy.context.scene.world or bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    bg = next((n for n in nt.nodes if n.type == "BACKGROUND"), None) or nt.nodes.new("ShaderNodeBackground")
    out = next((n for n in nt.nodes if n.type == "OUTPUT_WORLD"), None) or nt.nodes.new("ShaderNodeOutputWorld")
    if not bg.outputs["Background"].links:
        nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    env = nt.nodes.new("ShaderNodeTexEnvironment"); env.image = bpy.data.images.load(hdr, check_existing=True)
    tc = nt.nodes.new("ShaderNodeTexCoord"); mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Rotation"].default_value[2] = rng.uniform(0, 2 * math.pi)
    nt.links.new(tc.outputs["Generated"], mp.inputs["Vector"]); nt.links.new(mp.outputs["Vector"], env.inputs["Vector"])
    for l in list(bg.inputs["Color"].links):
        nt.links.remove(l)
    nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    stats["exterior"] = Path(hdr).name


def office_doors(rng, stats):
    """Commercial doors (critic r2-r5: maroon / green / dark rustic leaves in panel frames read as a house): every door leaf gets one
    neutral finish (white, light oak or grey), every casing brushed aluminium. Handles share the leaf material."""
    leaf_rgb = rng.choice(((0.86, 0.86, 0.84), (0.62, 0.5, 0.36), (0.5, 0.51, 0.52)))
    leaf = _mat("ir_office_door_leaf", leaf_rgb, 0.45)
    frame = _mat("ir_office_door_frame", (0.7, 0.7, 0.72), 0.35)
    frame.node_tree.nodes["Principled BSDF"].inputs["Metallic"].default_value = 1.0
    n = 0
    for o in bpy.data.objects:
        f = o.name.split("(")[0]
        if o.type != "MESH" or "Door" not in f:
            continue
        m = frame if "Casing" in f else leaf
        for sl in o.material_slots:              # lite / glass-panel leaves keep their glass, metal parts take the frame (floor A r2:
            name = sl.material.name.lower() if sl.material else ""   # glass painted over with the leaf colour read as a house panel door)
            if "glass" not in name:
                sl.material = frame if "metal" in name else m
        if not o.material_slots:
            o.data.materials.append(m)
        n += 1
    stats["office_doors"] = n
    w = 0                                                    # window frames / blinds: wood read as curtains in a house (critic r6)
    for o in bpy.data.objects:
        if o.type == "MESH" and "Window" in o.name.split("(")[0]:
            for sl in o.material_slots:
                if sl.material and "glass" not in sl.material.name.lower():
                    sl.material = frame
            w += 1
    stats["office_windows"] = w


ENTRANCE_STYLES = ("ramen", "shopfront_glass", "cafe_wood")


def _door_styles():
    """(interior style, entrance style) from the environment. DOOR_STYLE = office (default) | hotel | ramen | shopfront_glass | cafe_wood; DOOR_STYLE_INTERIOR / DOOR_STYLE_ENTRANCE override one kind. A street-entrance style
    (ramen, shopfront_glass, cafe_wood) leaves interior doors as plain oak; hotel styles every door (a door with no corridor side stays plain)."""
    import os
    st = os.environ.get("DOOR_STYLE", "office")
    inner = os.environ.get("DOOR_STYLE_INTERIOR") or ("oak" if st in ENTRANCE_STYLES else st)
    outer = os.environ.get("DOOR_STYLE_ENTRANCE") or st
    return inner, outer


def _door_parts(style, k):
    """Parts of one styled door leaf in the opening frame -> (keys, parts, mats). k: box(tm, zm, nn, wt, hz, dn), tc (leaf centre along the opening), W, H, T, z0, hinge (+1 / -1), sg_c (corridor face, 0 = none),
    ext (outward face of a street door, 0 = interior), plain (a bathroom door: no plaque / lock). Faces: nn > 0 is the +normal face. Boxes only, so every style is a few dozen primitives."""
    import os
    box, tc, W, H, T, z0, hinge, sg_c, ext, plain = k["box"], k["tc"], k["W"], k["H"], k["T"], k["z0"], k["hinge"], k["sg_c"], k["ext"], k["plain"]
    brass = pa._flat("ir_hotel_brass", (0.78, 0.6, 0.28), 0.3, 1.0)
    if style in ("hotel", "oak"):                                # hotel: dark walnut veneer, vertical grooves, brass lever + black card lock, corridor-face number plaque and peephole; oak: the same leaf in light oak, plain
        hot = style == "hotel"
        veneer = pa._flat("ir_hotel_door_veneer" if hot else "ir_oak_door_veneer", (0.2, 0.1, 0.05) if hot else (0.45, 0.28, 0.12), 0.5, wood=True)
        groove = pa._flat("ir_hotel_door_groove", (0.045, 0.02, 0.01), 0.6); cardblk = pa._flat("ir_hotel_card", (0.03, 0.03, 0.035), 0.4)
        lock = bool(hot and sg_c and not plain)
        parts = {"leaf": [box(tc, z0 + H / 2, 0, W, H, T)],
                 "groove": [box(tc - W / 2 + j * W / 6, z0 + H / 2, sg * (T / 2 + 0.0005), 0.007, H - 0.5, 0.002) for j in range(1, 6) for sg in (1, -1)] if hot else [],
                 "brass": [box(tc - hinge * (W / 2 - 0.09), z0 + 1.0, sg * (T / 2 + 0.035), 0.12, 0.018, 0.018) for sg in (1, -1)] +
                          [box(tc - hinge * (W / 2 - 0.06), z0 + 1.0, sg * (T / 2 + 0.008), 0.05, 0.15, 0.012) for sg in (1, -1)] +
                          [box(tc, z0 + 0.1, sg * (T / 2 + 0.002), W - 0.04, 0.2, 0.004) for sg in (1, -1)] +
                          ([box(tc + hinge * W * 0.28, z0 + 1.55, sg_c * (T / 2 + 0.004), 0.12, 0.06, 0.008), box(tc, z0 + 1.48, sg_c * (T / 2 + 0.004), 0.018, 0.018, 0.008)] if lock else []),
                 "card": [box(tc - hinge * (W / 2 - 0.06), z0 + 1.22, sg_c * (T / 2 + 0.014), 0.05, 0.1, 0.01)] if lock else []}
        return ("leaf", "groove", "brass", "card"), parts, [veneer, groove, brass, cardblk]
    glass = pa._flat("ir_door_vision_glass", (0.25, 0.3, 0.32), 0.05, transmission=0.85)
    sd = -hinge                                                  # a sliding leaf slides towards the side away from its hinge
    if style == "ramen":                                         # honey-oak sliding door: solid lower half, a kumiko lattice over glass in the upper half, slid 40 % open; an indigo noren on a rod, a wooden step, a paper lantern
        oak = pa._flat("ir_ramen_oak", (0.5, 0.31, 0.13), 0.5, wood=True); indigo = pa._flat("ir_noren_indigo", (0.012, 0.03, 0.11), 0.9); white = pa._flat("ir_noren_band", (0.85, 0.83, 0.78), 0.9)
        glow = pa._flat("ir_lantern_paper", (0.95, 0.75, 0.45), 0.8); gb = glow.node_tree.nodes["Principled BSDF"]
        gb.inputs["Emission Color"].default_value = (1.0, 0.72, 0.38, 1); gb.inputs["Emission Strength"].default_value = 3.0
        rod = pa._flat("ir_noren_rod", (0.1, 0.07, 0.04), 0.6)
        e = ext or 1
        cx, nn0 = tc + sd * W * float(__import__("os").environ.get("ROOM_RAMEN_DOOR_SLIDE") or 0.4), -e * 0.045                                       # the slid leaf stands just inside the plane of the wall
        frame = [box(cx, z0 + H / 2, nn0, 0.05, H, 0.04), box(cx + sd * (W / 2 - 0.025), z0 + H / 2, nn0, 0.05, H, 0.04), box(cx - sd * (W / 2 - 0.025), z0 + H / 2, nn0, 0.05, H, 0.04),
                 box(cx, z0 + 0.03, nn0, W, 0.06, 0.04), box(cx, z0 + H - 0.03, nn0, W, 0.06, 0.04), box(cx, z0 + H * 0.5, nn0, W, 0.05, 0.04),
                 box(cx, z0 + H * 0.25, nn0, W - 0.1, H * 0.46, 0.03)]                # the lower solid panel
        lat = [box(cx - W / 2 + 0.05 + j * (W - 0.1) / 9, z0 + H * 0.76, nn0 + e * 0.018, 0.012, H * 0.42, 0.012) for j in range(1, 9)] + \
              [box(cx, z0 + H * 0.56 + q * H * 0.4 / 5, nn0 + e * 0.018, W - 0.1, 0.012, 0.012) for q in range(1, 5)]
        gl = [box(cx, z0 + H * 0.76, nn0, W - 0.1, H * 0.42, 0.006)]
        n_, bands, step, rods, lant = [], [], [], [], []
        if ext:
            rz = z0 + H * 0.86; nz = -ext * (T / 2 + 0.12)                                  # the ROOM side of the door head (ext points outdoors; S32 r20: hung outside, invisible from inside), 12 cm off the wall plane so it clears the slid leaf and the casing
            n_ = [box(tc + (q - 1) * W * 0.3, rz - 0.27, nz, W * 0.3 - 0.02, 0.5, 0.004) for q in range(3)]       # three split panels, indigo, no text
            bands = [box(tc + (q - 1) * W * 0.3, rz - 0.47, nz + ext * 0.003, W * 0.3 - 0.02, 0.05, 0.004) for q in range(3)]    # one plain off-white band at each hem
            step = [box(tc, z0 + 0.02, ext * 0.17, W + 0.12, 0.04, 0.34)]
            rods = [box(tc, rz + 0.03, nz, W + 0.1, 0.02, 0.02)]
            lant = [box(tc + (W / 2 + 0.28), z0 + 1.75, ext * (T / 2 + 0.12), 0.17, 0.24, 0.17)]
        noren_png = Path(os.environ.get("ROOM_RAMEN_GRAPHICS") or "/jarvis/project/robomituba/data/venue_refs/ramen_shop_01/graphics") / "noren_01.png"
        if ext and n_ and noren_png.exists():                    # a generated noren picture (noren_01.png) across the three split panels: panel q shows the q-th third of the image (UV mapping), no hem band
            try:
                import bpy
                img = bpy.data.images.load(str(noren_png), check_existing=True); img.colorspace_settings.name = "sRGB"
                nm = []
                for q in range(3):
                    m_ = bpy.data.materials.get(f"ir_noren_dye_{q}")
                    if m_ is None:                                   # dyed cloth: the design shows on both faces (the UVs are per face, mirrored on the back; see the door assembly) and a little light passes through
                        m_ = bpy.data.materials.new(f"ir_noren_dye_{q}"); m_.use_nodes = True; nt_ = m_.node_tree; b_ = nt_.nodes["Principled BSDF"]; out_ = next(n_ for n_ in nt_.nodes if n_.type == "OUTPUT_MATERIAL")
                        uv_ = nt_.nodes.new("ShaderNodeUVMap"); tx_ = nt_.nodes.new("ShaderNodeTexImage"); tx_.image = img; tx_.extension = "EXTEND"
                        nt_.links.new(uv_.outputs["UV"], tx_.inputs["Vector"]); nt_.links.new(tx_.outputs["Color"], b_.inputs["Base Color"]); b_.inputs["Roughness"].default_value = 0.9
                        tr_ = nt_.nodes.new("ShaderNodeBsdfTranslucent"); mx_ = nt_.nodes.new("ShaderNodeMixShader"); mx_.inputs["Fac"].default_value = 0.25
                        nt_.links.new(tx_.outputs["Color"], tr_.inputs["Color"]); nt_.links.new(b_.outputs["BSDF"], mx_.inputs[1]); nt_.links.new(tr_.outputs["BSDF"], mx_.inputs[2]); nt_.links.new(mx_.outputs["Shader"], out_.inputs["Surface"])
                    nm.append(m_)
                return ("oak", "glass", "n0", "n1", "n2", "rod", "glow"), {"oak": frame + lat + step, "glass": gl, "n0": n_[0:1], "n1": n_[1:2], "n2": n_[2:3], "rod": rods, "glow": lant}, [oak, glass, nm[0], nm[1], nm[2], rod, glow]
            except Exception as ex:                              # noqa: BLE001 -- the abstract indigo noren stays
                print(f"[architecture_pass] noren image skipped: {ex!r}"[:160], flush=True)
        return ("oak", "glass", "indigo", "white", "rod", "glow"), {"oak": frame + lat + step, "glass": gl, "indigo": n_, "white": bands, "rod": rods, "glow": lant}, [oak, glass, indigo, white, rod, glow]
    if style == "shopfront_glass":                               # a full-height glass leaf in the shopfront's frame colour (BIGGLASS_FRAME_RGB), long vertical pull handles, slid 35 % open, a doormat inside
        rgb = tuple(float(v) for v in os.environ["BIGGLASS_FRAME_RGB"].split(",")) if os.environ.get("BIGGLASS_FRAME_RGB") else (0.30, 0.16, 0.09)
        fm = pa._flat("ir_bg_frame_" + "_".join(f"{v:.2f}" for v in rgb), rgb, 0.4, 0.5); mat = pa._flat("ir_doormat", (0.05, 0.05, 0.055), 0.95)
        cx, nn0 = tc + sd * W * 0.35, 0.05
        fr_ = [box(cx + q * (W / 2 - 0.03), z0 + H / 2, nn0, 0.06, H, 0.05) for q in (1, -1)] + [box(cx, z0 + 0.05, nn0, W, 0.1, 0.05), box(cx, z0 + H - 0.04, nn0, W, 0.08, 0.05)]
        gl = [box(cx, z0 + H / 2, nn0, W - 0.1, H - 0.14, 0.012)]
        pulls = [box(cx - sd * (W / 2 - 0.1), z0 + 1.05, nn0 + sg * 0.05, 0.03, 0.7, 0.03) for sg in (1, -1)]
        mats_ = [box(tc, z0 + 0.008, -(ext or 1) * 0.45, W * 0.85, 0.016, 0.6)]
        return ("frame", "glass", "brass", "mat"), {"frame": fr_, "glass": gl, "brass": pulls, "mat": mats_}, [fm, glass, brass, mat]
    oak = pa._flat("ir_cafe_oak", (0.42, 0.26, 0.11), 0.5, wood=True)         # cafe_wood: an oak leaf with a glazed upper half and a brass bar handle (a cafe / bar street door)
    fr_s = float(__import__("os").environ.get("ROOM_CAFE_DOOR_SLIDE") or 0.0)             # S31 r17: the street leaf filled the opening beside the curtain -> slid this fraction of its width along the wall (stands just inside the wall plane, like the ramen door)
    tc = tc + sd * W * fr_s; nn_ = -(ext or 1) * 0.06 if fr_s else 0
    parts = {"oak": [box(tc, z0 + H * 0.3, nn_, W, H * 0.6, T), box(tc - hinge * (W / 2 - 0.04), z0 + H * 0.8, nn_, 0.08, H * 0.4, T), box(tc + hinge * (W / 2 - 0.04), z0 + H * 0.8, nn_, 0.08, H * 0.4, T), box(tc, z0 + H - 0.04, nn_, W, 0.08, T)],
             "glass": [box(tc, z0 + H * 0.8, nn_, W - 0.16, H * 0.36, 0.01)],
             "brass": [box(tc - hinge * (W / 2 - 0.08), z0 + 1.0, nn_ + sg * (T / 2 + 0.04), 0.03, 0.5, 0.03) for sg in (1, -1)]}
    return ("oak", "glass", "brass"), parts, [oak, glass, brass]


def flush_doors(stats):
    """Every door leaf becomes a flush commercial leaf -- one slab, a narrow vision panel, a lever handle and a kick plate on both
    faces -- with the same hinge and swing. The Infinigen runtime (/root/module/infinigen) draws panelled, louvred, multi-lite and
    glass-panel leaves; critics read them as 'six-panel residential doors' (floors B, C, F3), 'a bank of steel lockers' (E3 r9) and
    'a free-standing wardrobe' (E3 r8). The closed pose is found the way room_dressing shuts exterior doors: the z rotation that lays
    the leaf thinnest across the wall normal, centred in the opening."""
    import bmesh
    leaf_m = bpy.data.materials.get("ir_office_door_leaf") or _mat("ir_office_door_leaf", (0.86, 0.86, 0.84), 0.45)
    glass = pa._flat("ir_door_vision_glass", (0.25, 0.3, 0.32), 0.05, transmission=0.85)
    chrome = pa._flat("ir_chrome", (0.8, 0.8, 0.82), 0.15, 1.0)
    n_done = 0
    svc = []                                                     # service rooms keep their doors shut: an open leaf standing in a small
    for nm, parts in rd._rooms().items():                        # stockroom or WC read as 'the door swings into the rack' (floor H
        if nm.split("_")[0] in ("restroom", "utility", "closet", "bathroom") and "floor" in parts:   # r15-r17, 3 of 3 each)
            pts = [parts["floor"].matrix_world @ Vector(c) for c in parts["floor"].bound_box]
            svc.append((min(q.x for q in pts), max(q.x for q in pts), min(q.y for q in pts), max(q.y for q in pts)))
    allf = []
    for nm, parts in rd._rooms().items():
        if "floor" in parts:
            pts = [parts["floor"].matrix_world @ Vector(c) for c in parts["floor"].bound_box]
            allf.append((min(q.x for q in pts), max(q.x for q in pts), min(q.y for q in pts), max(q.y for q in pts)))
    halls = []
    for nm, parts in rd._rooms().items():
        if nm.split("_")[0] == "hallway" and "floor" in parts:
            pts = [parts["floor"].matrix_world @ Vector(c) for c in parts["floor"].bound_box]
            halls.append((min(q.x for q in pts), max(q.x for q in pts), min(q.y for q in pts), max(q.y for q in pts)))
    n_shut = n_flip = 0
    for o in list(bpy.data.objects):
        f = o.name.split("(")[0]
        if o.type != "MESH" or "Door" not in f or "Casing" in f or o.parent is None or not o.data.polygons:
            continue
        c = o.parent.matrix_world.translation.copy()
        nrm = o.parent.matrix_world.to_3x3() @ Vector((0, 1, 0)); nrm.z = 0
        if nrm.length < 1e-6:
            continue
        nrm.normalize(); t = Vector((-nrm.y, nrm.x, 0))
        fs = [(pg.center.copy(), pg.area) for pg in o.data.polygons]
        A = sum(a for _, a in fs) or 1.0
        o.rotation_mode = "XYZ"
        rz0 = o.rotation_euler[2]
        def cost(rz):
            o.rotation_euler[2] = rz
            bpy.context.view_layer.update()
            M = o.matrix_world
            w = [((M @ q - c).dot(nrm), (M @ q - c).dot(t), a) for q, a in fs]
            mn = sum(x * a for x, _, a in w) / A
            return (sum(a * (x - mn) ** 2 for x, _, a in w) / A) ** 0.5 + 0.1 * abs(sum(y * a for _, y, a in w) / A)
        rzc = min((math.radians(d) for d in range(-180, 180, 2)), key=cost)
        o.rotation_euler[2] = rzc; bpy.context.view_layer.update()
        M = o.matrix_world.copy()
        vs = [M @ v.co for v in o.data.vertices]
        ts = [(v - c).dot(t) for v in vs]; ns = [(v - c).dot(nrm) for v in vs]; zs = [v.z for v in vs]
        t0, t1 = sorted(ts)[int(0.02 * len(ts))], sorted(ts)[int(0.98 * len(ts)) - 1]   # percentiles: handles stick out
        z0, z1 = min(zs), max(zs); nm = sum(ns) / len(ns)
        W, H, T = t1 - t0, z1 - z0, 0.045
        if W < 0.4 or H < 1.6:                                   # not a leaf (a fragment): leave it
            o.rotation_euler[2] = rz0
            continue
        hinge = 1 if (M.translation - c).dot(t) > (t0 + t1) / 2 else -1
        tc = (t0 + t1) / 2
        def box(tm, zm, nn, wt, hz, dn):                         # a box centred at (t, z, n) in the opening frame
            ctr = c + t * tm + nrm * (nm + nn); ctr.z = zm
            return ctr, (wt, hz, dn)
        parts = {"leaf": [box(tc, z0 + H / 2, 0, W, H, T)], "glass": [box(tc + hinge * W * 0.12, z0 + H * 0.62, 0, 0.14, H * 0.38, T + 0.006)],
                 "metal": [box(tc - hinge * (W / 2 - 0.09), z0 + 1.02, sg * (T / 2 + 0.03), 0.14, 0.02, 0.02) for sg in (1, -1)] +
                          [box(tc - hinge * (W / 2 - 0.03), z0 + 1.02, sg * (T / 2 + 0.015), 0.025, 0.06, 0.03) for sg in (1, -1)] +
                          [box(tc, z0 + 0.1, sg * (T / 2 + 0.002), W - 0.04, 0.2, 0.004) for sg in (1, -1)]}
        bm = bmesh.new()
        Minv = M.inverted()
        mats = [leaf_m, leaf_m if __import__("os").environ.get("DOOR_VISION") == "0" else glass, chrome]      # DOOR_VISION=0: a solid leaf, the vision panel takes the leaf finish (B r22: 'white doors with glazed inserts, want solid wood')
        keys_ = ("leaf", "glass", "metal")
        inner_, outer_ = _door_styles()
        hp_ = lambda p_: any(b[0] < p_.x < b[1] and b[2] < p_.y < b[3] for b in halls)
        fl_ = lambda p_: any(b[0] < p_.x < b[1] and b[2] < p_.y < b[3] for b in allf)
        ext_ = 1 if not fl_(c + nrm * 0.7) else -1 if not fl_(c - nrm * 0.7) else 0       # the outward face of a street door
        sty_ = outer_ if ext_ else inner_
        force_shut_ = False
        if sty_ != "office":                                  # a styled door (DOOR_STYLE*, see _door_parts)
            sg_c = 1 if hp_(c + nrm * 0.7) else -1 if hp_(c - nrm * 0.7) else 0                 # the corridor face of the leaf (0 = no corridor)
            bath_ = any(b[0] < q.x < b[1] and b[2] < q.y < b[3] for b in svc for q in (c + nrm * 0.7, c - nrm * 0.7))
            keys_, parts, mats = _door_parts(sty_, {"box": box, "tc": tc, "W": W, "H": H, "T": T, "z0": z0, "hinge": hinge, "sg_c": sg_c, "ext": ext_, "plain": bath_})
            force_shut_ = bool(ext_ and sty_ in ENTRANCE_STYLES)                                # a sliding street door stands in the wall plane
        uvl_ = bm.loops.layers.uv.verify()
        for slot, key in enumerate(keys_):
            for ctr, (wt, hz, dn) in parts[key]:
                r = bmesh.ops.create_cube(bm, size=1.0)
                [fc_.normal_update() for fc_ in {fc for v in r["verts"] for fc in v.link_faces}]
                fn_ = {fc: fc.normal.y for fc in {fc for v in r["verts"] for fc in v.link_faces}} if key in ("n0", "n1", "n2") else {}     # the noren panels: face side (+-nrm) before the transform
                lwm_ = {}
                for v in r["verts"]:                             # opening frame -> world -> the leaf's local frame
                    lw = ctr + t * (v.co.x * wt) + nrm * (v.co.y * dn) + Vector((0, 0, v.co.z * hz))
                    lwm_[v] = lw
                    v.co = Minv @ lw
                for fc in {fc for v in r["verts"] for fc in v.link_faces}:
                    fc.material_index = slot
                    if fn_:                                      # one picture across the three panels, upright from the side each face looks at, mirrored on the back (dyed cloth shows its design through)
                        sy_ = 1.0 if fn_[fc] >= 0 else -1.0
                        right_ = (-(nrm * sy_)).cross(Vector((0, 0, 1)))
                        sgn_ = 1.0 if t.dot(right_) > 0 else -1.0
                        t0_, S_, zb_ = tc - 0.45 * W, 0.9 * W, z0 + H * 0.86 - 0.52
                        for lp in fc.loops:
                            lw = lwm_[lp.vert]
                            u_ = min(max(((lw - c).dot(t) - t0_) / S_, 0.0), 1.0); u_ = u_ if sgn_ > 0 else 1.0 - u_
                            lp[uvl_].uv = (u_, min(max((lw.z - zb_) / 0.5, 0.0), 1.0))
        me = bpy.data.meshes.new(f"ir_flush_leaf_{n_done}")
        bm.to_mesh(me); bm.free()
        for m_ in mats:
            me.materials.append(m_)
        o.data = me
        shut = force_shut_ or any(b[0] < q.x < b[1] and b[2] < q.y < b[3] for b in svc for q in (c + nrm * 0.7, c - nrm * 0.7))
        o.rotation_euler[2] = rzc if shut else rz0               # shut into a service room, else back to its swing
        n_shut += shut
        if not shut and halls:                                   # a leaf open into the corridor half-blocked it (floor D3 r12, 3 of 3):
            bpy.context.view_layer.update()                      # swing it into the room instead
            m_ = o.matrix_world @ (sum((v.co for v in o.data.vertices), Vector()) / max(1, len(o.data.vertices)))
            if any(b[0] < m_.x < b[1] and b[2] < m_.y < b[3] for b in halls):
                o.rotation_euler[2] = 2 * rzc - rz0
                n_flip += 1
        n_done += 1
    bpy.context.view_layer.update()
    stats["flush_doors"] = n_done
    stats["service_doors_shut"] = n_shut
    stats["corridor_doors_flipped"] = n_flip


def frosted_restroom_windows(stats):
    """Restroom windows get obscure glass (floors C, D3, H: 'a large clear window beside the toilet', 3 of 3 calls each)."""
    blind = pa._flat("ir_venetian_slat", (0.78, 0.79, 0.8), 0.35, metallic=0.4)
    frost = pa._flat("ir_frosted_glass", (0.95, 0.96, 0.97), 0.75, transmission=0.7)   # 0.45 / 1.0 still read as clear (floor I r10, 2 of 3)
    boxes = []
    for nm, parts in rd._rooms().items():
        if nm.split("_")[0] in ("restroom", "bathroom", "closet") and "floor" in parts:   # changing rooms too: a fabric drape there read as
            # a bedroom (floor F3 r8, 3 of 3)
            pts = [parts["floor"].matrix_world @ Vector(c) for c in parts["floor"].bound_box]
            boxes.append((min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts)))
    n = 0
    for o in bpy.data.objects:
        if o.type != "MESH" or "Window" not in o.name.split("(")[0]:
            continue
        p = o.matrix_world @ (sum((Vector(c) for c in o.bound_box), Vector()) / 8)
        wp = [o.matrix_world @ Vector(c) for c in o.bound_box]
        along_y = max(q.x for q in wp) - min(q.x for q in wp) < max(q.y for q in wp) - min(q.y for q in wp)
        # 0.45 m out across the wall (an exterior window sits mid-wall, 0.31 m out: floor G), none along it -- a 0.45 m box margin also
        # took a neighbour's window past the corner and hung slats on a blank tiled wall (floor E3 r12, 3 of 3)
        m_x, m_y = (0.45, 0.0) if along_y else (0.0, 0.45)
        hit = next((b for b in boxes if b[0] - m_x < p.x < b[1] + m_x and b[2] - m_y < p.y < b[3] + m_y), None)
        if hit:
            for sl in o.material_slots:
                if sl.material and "glass" in sl.material.name.lower():
                    sl.material = frost
            # a roller blind over the whole opening on the room side: sun through the gap round the pane drew hard white L-shaped strips
            # on the floor (floor H r12, 3 of 3: 'a light leak')
            pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
            x0, x1 = min(q.x for q in pts), max(q.x for q in pts); y0, y1 = min(q.y for q in pts), max(q.y for q in pts)
            z0, z1 = min(q.z for q in pts), max(q.z for q in pts)
            rc = Vector(((hit[0] + hit[1]) / 2, (hit[2] + hit[3]) / 2, 0))
            # venetian slats, not one sheet: a flat white blind read as 'a blank white panel' (floor H r13, 3 of 3)
            nz = max(6, int((z1 - z0 + 0.08) / 0.05))
            zs = [z0 - 0.04 + (k + 0.5) * (z1 - z0 + 0.08) / nz for k in range(nz)]
            if x1 - x0 < y1 - y0:                                # the window runs along y: slats are thin x boxes on the room side
                xs = (x1 + 0.04) if rc.x > p.x else (x0 - 0.04)
                slats = [(xs, (y0 + y1) / 2, z, 0.04, y1 - y0 + 0.08, 0.004) for z in zs]
            else:
                ys = (y1 + 0.04) if rc.y > p.y else (y0 - 0.04)
                slats = [((x0 + x1) / 2, ys, z, x1 - x0 + 0.08, 0.04, 0.004) for z in zs]
            _box(f"RollerBlindFactory({n}).spawn_asset({n})", slats, blind)
            n += 1
    stats["frosted_windows"] = n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("blend"); ap.add_argument("--out", required=True); ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--palette", help="a style/spec json; its 'palette' (frame/structure/duct/accent linear RGB) overrides defaults")
    ap.add_argument("--exterior", help="equirect HDRI shown through the windows (world background colour)")
    ap.add_argument("--no-track", action="store_true", help="no track rails/spots (a sales floor is lit by an even fixture grid)")
    ap.add_argument("--archetype", default="default", choices=sorted(ARCHETYPES))
    a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])
    bpy.ops.wm.open_mainfile(filepath=a.blend)
    rng = random.Random(a.seed)
    pal = dict(PALETTE_DEFAULT)
    spec = json.loads(Path(a.palette).read_text()) if a.palette else {}
    pal.update(spec.get("palette", {}))
    kit = spec.get("architecture")                             # a style kit: the feature wall comes from rematerial, ducts follow the ceiling
    if kit and kit.get("ceiling") in ("exposed_dark", "dark_painted"):
        pal["duct"] = (0.03, 0.03, 0.032); pal["structure"] = (0.03, 0.03, 0.032)
    if spec.get("metal_finish") == "brass":
        pal["frame"] = (0.55, 0.38, 0.12)
    stats = {}
    scene, deps = bpy.context.scene, bpy.context.evaluated_depsgraph_get()
    for nm, parts in sorted(rd._rooms().items()):
        if "floor" not in parts or "wall" not in parts:
            continue
        room = fr.Room(nm, parts, scene, deps)
        if not kit and nm.split("_")[0] not in ("restroom", "utility", "closet", "kitchen", "hallway", "bathroom"):   # with a kit the feature
            # wall is rematerial's; never in service rooms (floor A2 r5: a charcoal wall in the tiled restroom)
            accent = _mat("ir_arch_accent", pal["accent"], 0.8)
            stats["accent"] = accent_wall(room, accent, rng, stats)
        build(room, rng, pal, stats, a.seed, track=not a.no_track, archetype=a.archetype)
    frosted_restroom_windows(stats)
    if a.archetype.startswith("office") or a.archetype == "warehouse" or kit:   # warehouse r3: mauve residential panel doors;
        # café N: 'a purple door frame' against a white/sage/oak kit -- any styled venue gets the neutral leaf and metal casing
        office_doors(rng, stats)
        flush_doors(stats)
    if a.archetype == "warehouse":                              # no skirting in an industrial unit (wh r22, 3 of 3: 'white skirting
        sk = [o for o in bpy.data.objects if o.name.startswith("skirtingboard")]   # boards on every wall say apartment')
        for o in sk:
            bpy.data.objects.remove(o, do_unlink=True)
        stats["skirting_removed"] = len(sk)
    if a.exterior:
        exterior(a.exterior, rng, stats)
    bpy.ops.wm.save_as_mainfile(filepath=a.out, compress=True)
    print("ARCH " + json.dumps(stats), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
