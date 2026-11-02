"""S35 strict round: bakery shell (ceiling clean-up, oak veneer walls, tiled piers, black-steel window shelf). Hooked from kit_lighting, idempotent (scene["ir_bk_shell"]).

ROOM_CEILING_CLEAN=1   delete CeilingBeam/Soffit/AboCeilingFixture/MfgVent, replace the ir_ceiling_point* spots by 3 black track runs x 6 spots (3000 K, ROOM_TRACK_W watts, default 90)
ROOM_WALL_VENEER=1     vertical oak veneer: 1.2 m panels with 5 mm reveals on the left / back / right walls (overlay boxes 12 mm thick)
ROOM_PIERS=1           two white 10 cm tile piers beside the shopfront window with a green band at 2.4 m
ROOM_WINDOW_SHELF=1    black steel 3-tier shelf with copper rails in front of the window
Room geometry is read from the break-room_0/0 ceiling/floor bbox; the shopfront (glass + door) is the low-y wall, the back wall with the fridges is high-y.
"""
from __future__ import annotations

import math
import os
import re

import bpy
from mathutils import Vector


def _bb(name):
    o = bpy.data.objects.get(name)
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]


def _tile_mat():
    m = bpy.data.materials.get("ir_bk_tile")
    if m is None:
        m = bpy.data.materials.new("ir_bk_tile"); m.use_nodes = True; N, L = m.node_tree.nodes, m.node_tree.links; b = N["Principled BSDF"]
        tc = N.new("ShaderNodeTexCoord"); br = N.new("ShaderNodeTexBrick"); mp = N.new("ShaderNodeMapping"); mp.inputs["Rotation"].default_value = (1.5708, 0.0, 0.0); L.new(tc.outputs["Object"], mp.inputs["Vector"]); L.new(mp.outputs["Vector"], br.inputs["Vector"])
        br.offset = 0.0; br.inputs["Color1"].default_value = (0.86, 0.86, 0.84, 1); br.inputs["Color2"].default_value = (0.82, 0.82, 0.80, 1); br.inputs["Mortar"].default_value = (0.45, 0.45, 0.43, 1)
        br.inputs["Scale"].default_value = 1.0; br.inputs["Mortar Size"].default_value = 0.012; br.inputs["Brick Width"].default_value = 0.1; br.inputs["Row Height"].default_value = 0.1
        L.new(br.outputs["Color"], b.inputs["Base Color"]); b.inputs["Roughness"].default_value = 0.3; b["weathered"] = True; m["weathered"] = True
    return m


def _clean_ceiling(zc, lo, hi, stats):
    n = 0
    for o in list(bpy.data.objects):
        if o.name.startswith(("CeilingBeamFactory", "SoffitFactory", "AboCeilingFixtureFactory", "MfgVent")):
            bpy.data.objects.remove(o, do_unlink=True); n += 1
    for lt in [o for o in bpy.data.objects if o.type == "LIGHT" and o.name.startswith("ir_ceiling_point")]:
        bpy.data.objects.remove(lt, do_unlink=True)
    from room_planner import proc_boutique_flagship as fl
    black = fl._flat("ir_bk_track", (0.02, 0.02, 0.022), 0.4, 1.0)
    W = float(os.environ.get("ROOM_TRACK_W") or 90)
    x0, x1, y0, y1 = lo[0] + 0.12, hi[0] - 0.12, lo[1] + 0.5, hi[1] - 0.6
    prims, heads = [], []
    for k in range(3):
        x = x0 + (x1 - x0) * (k + 0.5) / 3
        prims.append(("box", x, (y0 + y1) / 2, zc - 0.02, 0.03, y1 - y0, 0.03))
        for j in range(6):
            y = y0 + (y1 - y0) * (j + 0.5) / 6
            prims.append(("cyl", (x, y, zc - 0.04), (x, y, zc - 0.2), 0.045, 16)); prims.append(("box", x, y, zc - 0.045, 0.05, 0.05, 0.03)); heads.append((x, y))
    fl.mesh_object("BakeryTrackLights", [(black, prims)], bevel=False)
    for i, (x, y) in enumerate(heads):
        ld = bpy.data.lights.new(f"ir_track_spot_{i}", "SPOT"); ld.energy = W; ld.spot_size = math.radians(75); ld.spot_blend = 0.5; ld.color = (1.0, 0.71, 0.42); ld.shadow_soft_size = 0.04
        o = bpy.data.objects.new(f"ir_track_spot_{i}", ld); o.location = (x, y, zc - 0.2); bpy.context.scene.collection.objects.link(o)
    stats["bk_ceiling"] = {"removed": n, "spots": len(heads)}


def _veneer(lo, hi, zc, stats):
    import scanned_wood as sw
    from room_planner import proc_boutique_flagship as fl
    m = sw.material("oak_plank", size_m=1.0, tint=(1.0, 0.93, 0.8), rough=(0.4, 0.6), space="object", grain="z")
    z0, z1 = lo[2] + 0.02, zc - 0.14
    h = z1 - z0; pw = 1.2; t = 0.012; prims = []
    def run(a0, a1, fixed, along_x, sgn):
        n = max(1, int((a1 - a0) // pw)); w = (a1 - a0) / n
        for i in range(n):
            c = a0 + w * (i + 0.5); pw_ = w - 0.005
            prims.append(("box", c, fixed + sgn * t / 2, z0 + h / 2, pw_, t, h) if along_x else ("box", fixed + sgn * t / 2, c, z0 + h / 2, t, pw_, h))
    run(lo[0] + 0.12, hi[0] - 0.12, hi[1] - 0.005, True, -1)                                  # back wall (y = max)
    run(lo[1] + 0.4, hi[1] - 0.12, lo[0] + 0.005, False, 1)                                   # left wall
    run(lo[1] + 0.4, hi[1] - 0.12, hi[0] - 0.005, False, -1)                                  # right wall
    fl.mesh_object("BakeryVeneer", [(m, prims)], bevel=False); stats["bk_veneer"] = len(prims)


def _piers(lo, hi, stats):
    from room_planner import proc_boutique_flagship as fl
    wall = lo[1] + 0.005; tile = _tile_mat(); green = fl._flat("ir_bk_band", (0.03, 0.2, 0.1), 0.5)
    for cx in (0.34, 4.3):
        fl.mesh_object(f"BakeryPier({cx})", [(tile, [("box", cx, wall + 0.11, 1.32, 0.4, 0.22, 2.4)]), (green, [("box", cx, wall + 0.11, 2.4, 0.42, 0.24, 0.1)])], bevel=False)
    stats["bk_piers"] = 2


def _shelf(lo, stats):
    from room_planner import proc_boutique_flagship as fl
    steel = fl._flat("ir_bk_shelf_black", (0.02, 0.02, 0.022), 0.4, 1.0); cu = fl._flat("ir_bk_copper", (0.72, 0.38, 0.22), 0.3, 1.0)
    cx, y, w, d = 3.2, lo[1] + 0.12 + 0.2, 1.12, 0.3; bl, rl = [], []
    for z in (0.55, 1.0, 1.45):
        bl.append(("box", cx, y, z, w, d, 0.03))
        rl += [("cyl", (cx - w / 2, y + d / 2 - 0.01, z + 0.1), (cx + w / 2, y + d / 2 - 0.01, z + 0.1), 0.007, 8), ("cyl", (cx - w / 2, y - d / 2 + 0.01, z + 0.1), (cx + w / 2, y - d / 2 + 0.01, z + 0.1), 0.007, 8)]
    for sx in (-1, 1):
        for sy in (-1, 1):
            bl.append(("box", cx + sx * (w / 2 - 0.02), y + sy * (d / 2 - 0.02), 0.78, 0.035, 0.035, 1.56))
    import random
    rg = random.Random(35); crust = fl._flat("ir_bk_shelf_crust", (0.55, 0.30, 0.12), 0.7); wrap = fl._pa()._flat("ir_bk_shelf_wrap", (0.92, 0.94, 0.95), 0.1, transmission=0.8)
    kraft = fl._flat("ir_bk_shelf_kraft", (0.55, 0.40, 0.25), 0.8); dgreen = fl._flat("ir_bk_shelf_box_g", (0.04, 0.16, 0.09), 0.5); cream = fl._flat("ir_bk_shelf_box_c", (0.82, 0.76, 0.62), 0.6)
    jar = fl._flat("ir_bk_shelf_jar", (0.45, 0.07, 0.06), 0.15); jam2 = fl._flat("ir_bk_shelf_jar2", (0.75, 0.45, 0.05), 0.15); lid = fl._flat("ir_bk_shelf_lid", (0.7, 0.55, 0.2), 0.3, 1.0); rib = fl._flat("ir_bk_shelf_rib", (0.6, 0.1, 0.1), 0.5)
    G = {k: [] for k in ("crust", "wrap", "kraft", "dg", "cream", "jar", "jar2", "lid", "rib")}
    for ti, z in enumerate((0.55, 1.0, 1.45)):
        zt = z + 0.015; x = cx - w / 2 + 0.07
        kind = ("loaf", "jar", "box")[ti]                                                  # bottom: bagged loaves, middle: jars, top: gift boxes (a mix on each tier from the second pass)
        while x < cx + w / 2 - 0.08:
            k = kind if rg.random() < 0.7 else rg.choice(("loaf", "jar", "box"))
            if k == "loaf":
                ln = rg.uniform(0.24, 0.3); G["crust"].append(("cyl", (x, y, zt + 0.055), (x + ln, y, zt + 0.055), 0.055, 12)); G["wrap"].append(("box", x + ln / 2, y, zt + 0.07, ln + 0.04, 0.13, 0.14)); x += ln + 0.06
            elif k == "jar":
                G["jar" if rg.random() < 0.55 else "jar2"].append(("cyl", (x + 0.04, y, zt), (x + 0.04, y, zt + 0.11), 0.04, 14)); G["lid"].append(("cyl", (x + 0.04, y, zt + 0.11), (x + 0.04, y, zt + 0.125), 0.042, 14)); x += 0.1
            else:
                bw, bh = rg.uniform(0.14, 0.2), rg.uniform(0.08, 0.16); G[rg.choice(("kraft", "dg", "cream"))].append(("box", x + bw / 2, y, zt + bh / 2, bw, 0.14, bh)); G["rib"].append(("box", x + bw / 2, y, zt + bh / 2, 0.012, 0.145, bh + 0.002)); x += bw + 0.04
    fl.mesh_object("BakeryWindowShelfStock", [(crust, G["crust"]), (wrap, G["wrap"]), (kraft, G["kraft"]), (dgreen, G["dg"]), (cream, G["cream"]), (jar, G["jar"]), (jam2, G["jar2"]), (lid, G["lid"]), (rib, G["rib"])], bevel=False)
    fl.mesh_object("BakeryWindowShelf", [(steel, bl), (cu, rl)], bevel=False); stats["bk_shelf"] = 1


def _office_veneer(stats):
    """O4 SRF-01: every office_* room gets a broad vertical-oak veneer wall (1.2 m panels, 5 mm reveals) on its freest wall, skipping door / window spans and anything standing within 0.5 m of the wall plane."""
    import scanned_wood as sw
    from room_planner import proc_boutique_flagship as fl
    m = sw.material("oak_plank", size_m=1.0, tint=(1.0, 0.93, 0.8), rough=(0.4, 0.6), space="object", grain="z")
    objs = [o for o in bpy.data.objects if o.type == "MESH" and o.parent is None and not o.name.endswith((".floor", ".ceiling", ".wall", ".exterior", ".meshed", ".wall.001")) and not o.name.startswith(("OfficeVeneer", "BakeryVeneer")) and not re.match(r"^[a-z\-]+_\d+/\d+$", o.name)]
    bbs = []
    for o in objs:
        pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
        bbs.append((min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts), min(p.z for p in pts), max(p.z for p in pts), o.name))
    n = 0
    for f in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("office") and o.name.endswith(".floor")]:
        lo, hi = _bb(f.name); zc = lo[2] + 2.6
        try:
            _, ch = _bb(f.name.replace(".floor", ".ceiling")); zc = ch[2]
        except Exception:
            pass
        best = None
        for wid, (a0, a1, fx, ax) in {"S": (lo[0], hi[0], lo[1], 0), "N": (lo[0], hi[0], hi[1], 0), "W": (lo[1], hi[1], lo[0], 1), "E": (lo[1], hi[1], hi[0], 1)}.items():
            blocked = []
            for x0, x1, y0, y1, z0, z1, nm in bbs:
                if z1 < lo[2] + 0.3 or z0 > lo[2] + 2.2:
                    continue
                c0, c1, w0, w1 = (x0, x1, y0, y1) if ax == 0 else (y0, y1, x0, x1)
                door = "door" in nm.lower() or "window" in nm.lower()
                if not door and (z1 - z0 < 1.2 or z0 > lo[2] + 1.0):
                    continue                                                  # low / hanging clutter does not stop a veneer wall
                if (min(abs(w0 - fx), abs(w1 - fx)) < (0.4 if not door else 1.0) or w0 - 0.05 <= fx <= w1 + 0.05) and c1 > a0 and c0 < a1:
                    blocked.append((c0 - (0.1 if door else 0.05), c1 + (0.1 if door else 0.05)))
            blocked.sort(); cur = a0 + 0.15; free = []
            for b0, b1 in blocked + [(a1 - 0.15, a1)]:
                if b0 - cur >= 0.6:
                    free.append((cur, b0))
                cur = max(cur, b1)
            tot = sum(b - a for a, b in free)
            if free and (best is None or tot > best[0]):
                best = (tot, wid, free, fx, ax)
        if best is None:
            continue
        _, wid, free, fx, ax = best; sgn = 1 if wid in ("S", "W") else -1; t = 0.012; z0, z1 = lo[2] + 0.02, zc - 0.14; h = z1 - z0; prims = []
        for a, b in free:
            k = max(1, int((b - a) // 1.2)); w = (b - a) / k
            for i in range(k):
                c = a + w * (i + 0.5); pw_ = w - 0.005; wl = fx + sgn * (0.005 + t / 2)
                prims.append(("box", c, wl, z0 + h / 2, pw_, t, h) if ax == 0 else ("box", wl, c, z0 + h / 2, t, pw_, h))
        fl.mesh_object(f"OfficeVeneer({f.name})", [(m, prims)], bevel=False); n += 1
    stats["office_veneer"] = n


def apply(stats):
    if bpy.context.scene.get("ir_bk_shell"):
        return 0
    n = 0
    if os.environ.get("ROOM_OFFICE_VENEER") == "1":
        _office_veneer(stats); n += 1
    if bpy.data.objects.get("break-room_0/0.floor") is None:
        bpy.context.scene["ir_bk_shell"] = 1; return n
    lo, hi = _bb("break-room_0/0.floor"); _, ch = _bb("break-room_0/0.ceiling"); zc = ch[2]
    if os.environ.get("ROOM_CEILING_CLEAN") == "1":
        _clean_ceiling(zc, lo, hi, stats); n += 1
    if os.environ.get("ROOM_WALL_VENEER") == "1":
        _veneer(lo, hi, zc, stats); n += 1
    if os.environ.get("ROOM_PIERS") == "1":
        _piers(lo, hi, stats); n += 1
    if os.environ.get("ROOM_WINDOW_SHELF") == "1":
        _shelf(lo, stats); n += 1
    bpy.context.scene["ir_bk_shell"] = 1
    return n
