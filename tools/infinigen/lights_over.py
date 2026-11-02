"""Hand-placed pendants over the sofa and the dining table (P2b refs: 'fabric drum pendants' in the living room, 'a long linear pendant' over the dining table). ceiling_fixtures.dress picks a fixture KIND at random
(living: chandelier 40 % else flush), so the kit's living_pendant / dining_pendant keys placed nothing in the P2b full round; this pass does not depend on that choice and runs in the kit stage (per-room rounds too).

Env (kit_lighting hook): ROOM_DRUM_PENDANT=living-room   room-name prefixes: the room's ABO ceiling fixtures are removed and ONE drum pendant (0.7 m, translucent cream) hangs over the sofa (else the room centre)
                         ROOM_LINEAR_PENDANT=dining-room one linear pendant (1.5 m) hangs over the dining table's centre, along its long axis, bar 0.85 m above the table top
Stats: stats["lights_over"] = {"drum": n, "linear": n}.
"""
from __future__ import annotations

import math
import os

import bpy
from mathutils import Vector


def _bb(o):
    p = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return min(q.x for q in p), max(q.x for q in p), min(q.y for q in p), max(q.y for q in p), min(q.z for q in p), max(q.z for q in p)


def apply(stats):
    from room_planner import proc_home as ph
    from room_planner import terrace_open as to
    import room_dressing as rd
    drum = tuple(x for x in os.environ.get("ROOM_DRUM_PENDANT", "").split(",") if x)
    lin = tuple(x for x in os.environ.get("ROOM_LINEAR_PENDANT", "").split(",") if x)
    out = {"drum": 0, "linear": 0}
    domes = tuple(x for x in os.environ.get("ROOM_DOME_ROOMS", "").split(",") if x)             # ROOM_DOME_ROOMS=break-room_0/0: black dome pendants over the counter / tables when the activity stage left none
    noflush = tuple(x for x in os.environ.get("ROOM_NO_ABO_FIXTURES", "").split(",") if x)              # ROOM_NO_ABO_FIXTURES=break-room_0/0: remove the room's stock (ABO) ceiling fixtures, e.g. keep only the kit's dome pendants
    for rname, parts in rd._rooms().items():
        if "floor" not in parts or "wall" not in parts:
            continue
        x0, x1, y0, y1, fz = to._bbox(parts["floor"]); wl = parts["wall"]
        zc = max((wl.matrix_world @ Vector(c)).z for c in wl.bound_box)
        inside = lambda o: x0 - 0.2 <= o.matrix_world.translation.x <= x1 + 0.2 and y0 - 0.2 <= o.matrix_world.translation.y <= y1 + 0.2
        if noflush and rname.startswith(noflush):
            for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("AboCeilingFixture") and inside(o)]:
                bpy.data.objects.remove(o, do_unlink=True)
        if domes and rname.startswith(domes):                    # H r71: no black dome pendants over the counter and tables (the activity-stage dress did not hang them): hang them here, once
            from room_planner import proc_assets
            shade = proc_assets.STYLE.get("pendant_shade")
            if shade and not any(o.name.startswith("DomePendantFactory") and inside(o) for o in bpy.data.objects if o.type == "MESH"):
                tops = [o for o in bpy.data.objects if o.type == "MESH" and inside(o) and (o.name.startswith("CafeCounterFactory") or o.name.startswith("CafeTableFactory"))]
                tabs = [t for t in tops if t.name.startswith("CafeTableFactory")][::2][:7]
                for t in [x for x in tops if x.name.startswith("CafeCounterFactory")] + tabs:
                    tx0, tx1, ty0, ty1, _, tz1 = _bb(t); is_c = t.name.startswith("CafeCounterFactory"); n = 3 if is_c else 1
                    long_x = (tx1 - tx0) >= (ty1 - ty0)
                    for k in range(n):
                        u = (k + 0.5) / n; px = tx0 + u * (tx1 - tx0) if long_x else (tx0 + tx1) / 2; py = (ty0 + ty1) / 2 if long_x else ty0 + u * (ty1 - ty0)
                        drop = max(0.5, min(1.2, zc - (tz1 + (0.9 if is_c else 0.75)) - 0.25))
                        o = proc_assets.DomePendantFactory(0, shade, drop).spawn_asset(out.setdefault("dome", 0))
                        bx0, bx1, by0, by1, _, bz1 = _bb(o); o.location += Vector((px - (bx0 + bx1) / 2, py - (by0 + by1) / 2, zc - 0.005 - bz1))
                        ld = bpy.data.lights.new("ir_dome_point", "POINT"); ld.energy = 60.0; ld.shadow_soft_size = 0.05
                        lo = bpy.data.objects.new(f"PointLampFactory(dome).spawn_asset({out['dome']})", ld); bpy.context.scene.collection.objects.link(lo)
                        bpy.context.view_layer.update(); lo.location = (px, py, _bb(o)[4] - 0.02); out["dome"] += 1
        if rname.startswith(drum) and drum:
            for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("AboCeilingFixture") and inside(o)]:
                bpy.data.objects.remove(o, do_unlink=True)
            sofa = next((o for o in bpy.data.objects if o.type == "MESH" and ("Sofa" in o.name or "Sectional" in o.name) and inside(o)), None)
            if sofa is not None:
                bx0, bx1, by0, by1, _, _ = _bb(sofa); cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
            else:
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            d = 0.75
            o = ph.DrumPendantFactory(0, d).spawn_asset(out["drum"])
            o.location = (cx, cy, zc - 0.005); out["drum"] += 1
        if rname.startswith(lin) and lin:
            tab = next((o for o in bpy.data.objects if o.type == "MESH" and ("DiningTable" in o.name or "TableDining" in o.name) and inside(o)), None)
            if tab is None:
                continue
            bx0, bx1, by0, by1, bz0, bz1 = _bb(tab); cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
            d = max(0.5, zc - bz1 - 0.85)
            o = ph.LinearPendantFactory(0, d).spawn_asset(out["linear"])
            if (bx1 - bx0) > (by1 - by0):                       # the table runs along x: turn the bar (it runs along local y)
                o.rotation_euler = (0, 0, math.pi / 2)
            o.location = (cx, cy, zc - 0.005); out["linear"] += 1
    bpy.context.view_layer.update()
    stats["lights_over"] = out
    return out["drum"] + out["linear"] + out.get("dome", 0)
