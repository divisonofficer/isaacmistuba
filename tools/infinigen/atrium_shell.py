"""S36 r6 (user: 'white walls are bland / the ceiling lighting does not suit an office auditorium'). Kit stage, idempotent (scene["ir_atrium_shell"]); each part has its own flag.

ROOM_ATRIUM_CEIL=1   remove track rails / spots / cassettes / sprinklers and the ceiling point lights; flat ceiling with a grid of recessed warm (3000 K) downlights (ROOM_ATRIUM_PITCH, default 2.5 m,
                     ROOM_ATRIUM_DL_W watts per spot, default 220), three linear slot lights over the lounge zone and a soft uplight at the foot of each ColumnFactory / RoundPillarFactory
ROOM_ATRIUM_CLAD=1   charcoal wall cladding (1.2 m vertical panels, 6 mm joints, rough 0.35) on the south wall (the entrance span is left clear) and the north corners beside the glass
ROOM_ATRIUM_WEST=1   a second full-height curtain wall on the west side (terrace_open._glaze, run at kit stage; tested: works without the arch stage; set BIGGLASS_FRAME_RGB=0.08,0.08,0.085 for dark mullions on both walls)
ROOM_ATRIUM_NICHES=1 the BookWall bookcases under the mezzanine become walnut with a walnut surround (uprights + head beam), reading as built-in bays
Room geometry comes from break-room_0/0.floor / .ceiling.
"""
from __future__ import annotations

import math
import os

import bpy
from mathutils import Vector

ROOM = "break-room_0/0"


def _bb(o):
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]


def _emit(name, rgb, strength):
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name); m.use_nodes = True; b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Emission Color"].default_value = (*rgb, 1); b.inputs["Emission Strength"].default_value = strength; b["weathered"] = True; m["weathered"] = True
    return m


def _spot(name, loc, rot, watts, deg, color=(1.0, 0.71, 0.42)):
    ld = bpy.data.lights.new(name, "SPOT"); ld.energy = watts; ld.spot_size = math.radians(deg); ld.spot_blend = 0.6; ld.color = color; ld.shadow_soft_size = 0.05
    o = bpy.data.objects.new(name, ld); o.location = loc; o.rotation_euler = rot; bpy.context.scene.collection.objects.link(o)


def _ceiling(lo, hi, zc, stats):
    from room_planner import proc_boutique_flagship as fl
    gone = 0
    for o in list(bpy.data.objects):
        if o.name.startswith(("TrackRailFactory", "TrackSpotFactory", "AcCassetteFactory", "SprinklerFactory")) or (o.type == "LIGHT" and o.name.startswith(("ir_ceiling_point", "ir_track"))):
            bpy.data.objects.remove(o, do_unlink=True); gone += 1
    pitch = float(os.environ.get("ROOM_ATRIUM_PITCH") or 2.5); W = float(os.environ.get("ROOM_ATRIUM_DL_W") or 220)
    nx = max(1, int((hi[0] - lo[0] - 1.0) // pitch) + 1); ny = max(1, int((hi[1] - lo[1] - 1.0) // pitch) + 1)
    x0 = (lo[0] + hi[0]) / 2 - pitch * (nx - 1) / 2; y0 = (lo[1] + hi[1]) / 2 - pitch * (ny - 1) / 2
    trim = fl._flat("ir_at_trim", (0.9, 0.9, 0.88), 0.5); lamp = _emit("ir_at_dl_emit", (1.0, 0.76, 0.5), 25.0); prim, lit, k = [], [], 0
    for i in range(nx):
        for j in range(ny):
            x, y = x0 + i * pitch, y0 + j * pitch
            prim.append(("cyl", (x, y, zc - 0.012), (x, y, zc - 0.002), 0.085, 20)); lit.append(("cyl", (x, y, zc - 0.016), (x, y, zc - 0.012), 0.065, 20))
            _spot(f"ir_at_dl_{k}", (x, y, zc - 0.03), (0, 0, 0), W, 70); k += 1
    slots = []
    for yy in (lo[1] + (hi[1] - lo[1]) * 0.25, lo[1] + (hi[1] - lo[1]) * 0.45, lo[1] + (hi[1] - lo[1]) * 0.62):
        xc = lo[0] + (hi[0] - lo[0]) * 0.36; ln = 5.0
        slots.append(("box", xc, yy, zc - 0.03, ln, 0.12, 0.05))
        al = bpy.data.lights.new(f"ir_at_slot_{len(slots)}", "AREA"); al.shape = "RECTANGLE"; al.size = ln; al.size_y = 0.12; al.energy = 220.0; al.color = (1.0, 0.8, 0.6)
        ao = bpy.data.objects.new(al.name, al); ao.location = (xc, yy, zc - 0.06); bpy.context.scene.collection.objects.link(ao)
    fl.mesh_object("AtriumDownlights", [(trim, prim), (lamp, lit + slots)], bevel=False)
    up = 0
    for o in list(bpy.data.objects):
        if o.type == "MESH" and o.name.startswith(("ColumnFactory", "RoundPillarFactory")):
            a, b = _bb(o)
            _spot(f"ir_at_up_{up}", ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - (b[1] - a[1]) / 2 - 0.15, 0.12), (math.pi, 0, 0), 80, 55, (1.0, 0.78, 0.55)); up += 1
    stats["atrium_ceiling"] = {"removed": gone, "downlights": k, "slots": len(slots), "uplights": up}


def _clad(lo, hi, zc, stats):
    from room_planner import proc_boutique_flagship as fl
    m = fl._flat("ir_at_clad", (0.055, 0.055, 0.06), 0.35); m["weathered"] = True
    z0, z1 = lo[2] + 0.02, zc - 0.05; h = z1 - z0; t = 0.02; prims = []
    cx = (lo[0] + hi[0]) / 2; door = (cx - 2.2, cx + 2.2)
    n = int((hi[0] - lo[0]) // 1.2); w = (hi[0] - lo[0]) / n
    for i in range(n):
        a, b = lo[0] + i * w, lo[0] + (i + 1) * w
        if b > door[0] and a < door[1]:
            continue
        prims.append(("box", (a + b) / 2, lo[1] + 0.31 + t / 2, z0 + h / 2, w - 0.006, t, h))                                  # in front of the 0.3 m pilasters: the whole south wall reads as charcoal cladding
    for sx in (1, -1):                                                                        # north corners beside the glass: a 0.6 m return on the north face of each corner pier
        xc = lo[0] + 0.3 if sx > 0 else hi[0] - 0.3
        prims.append(("box", xc, hi[1] - 0.14 - t / 2, z0 + h / 2, 0.6, t, h))
    fl.mesh_object("AtriumCladding", [(m, prims)], bevel=False); stats["atrium_clad"] = len(prims)


def _niches(lo, hi, stats):
    import scanned_wood as sw
    from room_planner import proc_boutique_flagship as fl
    walnut = sw.material("walnut", size_m=1.0, tint=(1.0, 0.9, 0.8), rough=(0.4, 0.6), space="object", grain="z"); swapped = 0; ys = []
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name.startswith("BookWallFactory"):
            a, b = _bb(o); ys += [a[1], b[1]]; xr = (a[0], b[0])
            for sl in o.material_slots:
                nm = (sl.material.name if sl.material else "").lower()
                if sl.material is not None and any(k in nm for k in ("oak", "wood", "bw_", "shelf", "case")) and "book" not in nm:
                    sl.material = walnut; swapped += 1
    if not ys:
        return
    y0, y1 = min(ys), max(ys); x1 = hi[0]; dx = x1 - xr[0]; zt = 2.6; prims = []
    nb = 3
    for k in range(nb + 1):
        prims.append(("box", x1 - dx / 2, y0 + (y1 - y0) * k / nb, zt / 2, dx, 0.06, zt))
    prims.append(("box", x1 - dx / 2, (y0 + y1) / 2, zt + 0.03, dx, y1 - y0 + 0.06, 0.06))
    fl.mesh_object("AtriumNicheSurround", [(walnut, prims)], bevel=False); stats["atrium_niches"] = {"slots": swapped}


def _bench_dress(stats):
    """S36 r8 CNT-01: the glass bench on the round rug was empty -> a book stack, a coffee cup and a small potted plant on top of each GlassBenchFactory."""
    from room_planner import proc_boutique_flagship as fl
    cover = [fl._flat(f"ir_bn_book{k}", c, 0.6) for k, c in enumerate(((0.45, 0.08, 0.07), (0.05, 0.17, 0.32), (0.85, 0.8, 0.68)))]
    white = fl._flat("ir_bn_cup", (0.92, 0.92, 0.9), 0.25); coffee = fl._flat("ir_bn_coffee", (0.09, 0.05, 0.03), 0.3); pot = fl._flat("ir_bn_pot", (0.72, 0.38, 0.24), 0.7)
    leaf = fl._flat("ir_bn_leaf", (0.05, 0.25, 0.05), 0.55); n = 0
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("GlassBenchFactory")]:
        pts = [o.matrix_world @ Vector(c) for c in o.bound_box]; top = max(p.z for p in pts)
        cx, cy = sum(p.x for p in pts) / 8, sum(p.y for p in pts) / 8
        alx = (max(p.x for p in pts) - min(p.x for p in pts)) >= (max(p.y for p in pts) - min(p.y for p in pts))
        at = lambda u: (cx + u, cy) if alx else (cx, cy + u)
        books = [("box", *at(-0.45), top + 0.02 + 0.04 * k, 0.26 - 0.02 * k, 0.19, 0.04, 0.1 * k - 0.15 if k else 0.0) for k in range(3)]
        x, y = at(0.0); cup = [("cyl", (x, y, top), (x, y, top + 0.09), 0.04, 20)]; liq = [("cyl", (x, y, top + 0.085), (x, y, top + 0.092), 0.034, 20)]
        x, y = at(0.42); pots = [("cyl", (x, y, top), (x, y, top + 0.14), 0.07, 20)]
        fl.mesh_object(f"BenchDressing({o.name})", [(cover[0], books[:1]), (cover[1], books[1:2]), (cover[2], books[2:]), (white, cup), (coffee, liq), (pot, pots)], bevel=False)
        import bmesh, random
        bm = bmesh.new(); rg = random.Random(3)
        bmesh.ops.create_icosphere(bm, subdivisions=3, radius=0.11)
        for v in bm.verts:
            v.co *= rg.uniform(0.72, 1.25); v.co.z *= 0.85
        me = bpy.data.meshes.new("BenchPlantFoliage"); bm.to_mesh(me); bm.free(); me.materials.append(leaf)
        for pl in me.polygons:
            pl.use_smooth = True
        fo = bpy.data.objects.new(f"BenchPlant({o.name})", me); fo.location = (x, y, top + 0.24); bpy.context.scene.collection.objects.link(fo)
        n += 1
    stats["atrium_bench"] = n


def apply(stats):
    if bpy.context.scene.get("ir_atrium_shell"):
        return 0
    f = bpy.data.objects.get(f"{ROOM}.floor"); c = bpy.data.objects.get(f"{ROOM}.ceiling")
    if f is None or c is None:
        return 0
    lo, hi = _bb(f); zc = _bb(c)[1][2]; n = 0
    if os.environ.get("ROOM_ATRIUM_WEST") == "1":
        import random
        from room_planner import terrace_open as to
        bb, fz, _ = to._sides(ROOM)
        if bb is not None:
            prev = stats.get("bigglass")
            ok_ = bool(to._glaze(ROOM, bb, fz, zc, "W", stats, random.Random(7))); n += 1
            wv = [dict(v, name=v["name"].replace("bigglass_", "west_")) for v in (stats.get("bigglass") or {}).get("views", [])]
            for v in wv:
                if v["name"] in ("west_a", "west_b"):                                      # r7: west_a stood inside a big HSSD plant; the corner views move 1.5 m into the room
                    v["location"][0] = round(v["location"][0] + 1.5, 2)
            if prev is not None:
                stats["bigglass"] = prev
            stats["atrium_west"] = {"ok": ok_, "views": wv}
            try:                                                                  # probe views facing the west curtain wall, next to the blend (same VIEWS dict format as bigglass_a/b/c)
                import json
                json.dump(wv, open(os.path.join(os.path.dirname(bpy.data.filepath) or "/tmp", "west_views.json"), "w"), indent=1)
            except Exception:
                pass
    for flag, fn in (("ROOM_ATRIUM_CEIL", lambda: _ceiling(lo, hi, zc, stats)), ("ROOM_ATRIUM_CLAD", lambda: _clad(lo, hi, zc, stats)), ("ROOM_ATRIUM_NICHES", lambda: _niches(lo, hi, stats)), ("ROOM_ATRIUM_BENCH", lambda: _bench_dress(stats))):
        if os.environ.get(flag) == "1":
            fn(); n += 1
    bpy.context.scene["ir_atrium_shell"] = 1
    return n
