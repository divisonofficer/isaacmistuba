"""Underground car-park fixtures (user 10-24: 'the ancillary fixtures of the car park are not realistic enough'). Hooked from kit_lighting after the ROOM_MODE ceiling hook, only when ROOM_PARKING_FIXTURES=1; no readable text.

For the largest room (the same one parking_ceiling.py dresses; u runs along its long axis, bays are 2.6 x 5 m, 16 m bands: bay row / 6 m aisle / bay row) and the pedestrian lobby (hallway rooms):
  columns       a yellow / black hazard-stripe wrap round the lower 1.0 m of every column, steel corner guards, a painted white level / bay band (no digits) at 1.5 m
  fire safety   a fire-extinguisher cabinet (red box, glass front, white sign above) and a hose reel (red drum + hose coil) on alternate columns, facing the aisle
  services      a galvanised cable tray (side rails + rungs) along each aisle side with hangers every 2 m, two jet fans per aisle (galvanised cylinder, bell mouths, hangers), straps and hangers on the red sprinkler pipe,
                a grey housing and two cables behind every linear LED tube
  signs         blue direction / level boards (white bars, no text) at both aisle ends
  equipment     a pay station (dark body, screen, card slot, ticket slot) and two EV chargers (white / green body, cable loop, bollard) near the first columns
  floor         a slotted drain channel along each aisle (0.3 m dark grate with bars), oil stains under 40 % of the cars and two long tyre-mark streaks per aisle (flat dark discs / strips, 1 mm proud)
  windows       photo-card windows are removed from the car park and the wall opening is plugged with concrete (there are no windows underground)
  lobby         hallway rooms: a flat white drop ceiling 12 cm under the soffit, hung rods / cords inside the lobby removed
Idempotent: previous ParkingFixtures(...) objects are deleted first."""
from __future__ import annotations

import math
import os
import random

import bmesh
import bpy
from mathutils import Vector

import room_dressing as rd
from room_planner import proc_assets as pa

BAY_W, BAY_D, AISLE, BAND = 2.6, 5.0, 6.0, 16.0


def _mats():
    em = lambda n, rgb, st: _emit(pa._flat(n, rgb, 0.4), rgb, st)
    return {"yel": pa._flat("ir_pf_yellow", (0.9, 0.7, 0.04), 0.6), "blk": pa._flat("ir_pf_black", (0.03, 0.03, 0.035), 0.7), "gal": pa._flat("ir_pf_galv", (0.62, 0.64, 0.66), 0.3, 0.9),
            "red": pa._flat("ir_pf_red", (0.72, 0.07, 0.05), 0.5, 0.2), "wht": pa._flat("ir_pf_white", (0.9, 0.9, 0.88), 0.55), "blu": pa._flat("ir_pf_blue", (0.05, 0.2, 0.55), 0.5),
            "gry": pa._flat("ir_pf_grey", (0.25, 0.26, 0.28), 0.5, 0.4), "grn": em("ir_pf_green", (0.1, 0.9, 0.3), 5.0), "scr": em("ir_pf_screen", (0.2, 0.55, 1.0), 3.0),
            "glass": pa._flat("ir_pf_glass", (0.8, 0.9, 0.95), 0.05), "oil": pa._flat("ir_pf_oil", (0.05, 0.05, 0.055), 0.25), "tyre": pa._flat("ir_pf_tyre", (0.08, 0.08, 0.085), 0.55),
            "conc": pa._flat("ir_pf_concrete", (0.5, 0.5, 0.48), 0.9), "drain": pa._flat("ir_pf_drain", (0.03, 0.03, 0.032), 0.6, 0.2), "wet": pa._flat("ir_pf_wet", (0.012, 0.012, 0.014), 0.45, 0.0), "ceil": pa._flat("ir_pf_ceiling", (0.88, 0.88, 0.86), 0.7)}


def _emit(m, rgb, st):
    b = m.node_tree.nodes["Principled BSDF"]; b.inputs["Emission Color"].default_value = (*rgb, 1); b.inputs["Emission Strength"].default_value = st
    return m


class B:
    """A bmesh with a material list; box / cyl / disc in world coordinates."""

    def __init__(self, mats):
        self.bm = bmesh.new(); self.keys = list(mats); self.mats = mats

    def _slot(self, k, f):
        for f_ in {f_ for v in f for f_ in v.link_faces}:
            f_.material_index = self.keys.index(k)

    def box(self, c, s, k, yaw=0.0):
        r = bmesh.ops.create_cube(self.bm, size=1.0); bmesh.ops.scale(self.bm, vec=s, verts=r["verts"])
        if yaw:
            bmesh.ops.rotate(self.bm, cent=(0, 0, 0), matrix=__import__("mathutils").Matrix.Rotation(yaw, 3, "Z"), verts=r["verts"])
        bmesh.ops.translate(self.bm, vec=c, verts=r["verts"]); self._slot(k, r["verts"])

    def cyl(self, c, rad, ln, k, axis="z", seg=14, rad2=None):
        r = bmesh.ops.create_cone(self.bm, cap_ends=True, segments=seg, radius1=rad, radius2=rad if rad2 is None else rad2, depth=ln)
        M = __import__("mathutils").Matrix
        if axis == "x":
            bmesh.ops.rotate(self.bm, cent=(0, 0, 0), matrix=M.Rotation(math.pi / 2, 3, "Y"), verts=r["verts"])
        elif axis == "y":
            bmesh.ops.rotate(self.bm, cent=(0, 0, 0), matrix=M.Rotation(math.pi / 2, 3, "X"), verts=r["verts"])
        bmesh.ops.translate(self.bm, vec=c, verts=r["verts"]); self._slot(k, r["verts"])

    def make(self, name):
        me = bpy.data.meshes.new(name); self.bm.to_mesh(me); self.bm.free()
        for k in self.keys:
            me.materials.append(self.mats[k])
        o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
        for p in me.polygons:
            p.use_smooth = False
        return o


def _bbox(o):
    q = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return min(v.x for v in q), max(v.x for v in q), min(v.y for v in q), max(v.y for v in q), min(v.z for v in q), max(v.z for v in q)


def apply(stats):
    for o in [o for o in bpy.data.objects if o.name.startswith("ParkingFixtures(")]:
        bpy.data.objects.remove(o, do_unlink=True)
    rooms = rd._rooms()
    big = [(n, p) for n, p in rooms.items() if "floor" in p and "wall" in p]
    if not big:
        return 0
    name, parts = max(big, key=lambda np_: np_[1]["floor"].dimensions.x * np_[1]["floor"].dimensions.y)
    fx0, fx1, fy0, fy1, fz, _t = _bbox(parts["floor"]); zc = _bbox(parts["wall"])[5]
    along_x = (fx1 - fx0) >= (fy1 - fy0); L = (fx1 - fx0) if along_x else (fy1 - fy0); S = (fy1 - fy0) if along_x else (fx1 - fx0)
    loc = lambda u, v, z: Vector((fx0 + u, fy0 + v, z)) if along_x else Vector((fx0 + v, fy0 + u, z))
    uv = lambda p: ((p.x - fx0), (p.y - fy0)) if along_x else ((p.y - fy0), (p.x - fx0))
    M = _mats(); keys = list(M)
    b = B(M); rng = random.Random(len(bpy.data.objects))
    bands = max(1, int((S - 0.3) // BAND)) if S >= BAND else 1
    avs = [0.25 + k * BAND + BAY_D + AISLE / 2 for k in range(bands)]
    # --- columns: hazard wrap, fire cabinets / hose reels, level bands
    cols = [o for o in bpy.data.objects if o.type == "MESH" and o.parent is None and o.name.split("(")[0] in ("ColumnWithPlateFactory", "ColumnFactory") and fx0 - 0.3 <= o.matrix_world.translation.x <= fx1 + 0.3 and fy0 - 0.3 <= o.matrix_world.translation.y <= fy1 + 0.3]
    n_fire = 0
    for i, c in enumerate(cols):
        x0, x1, y0, y1, z0, z1 = _bbox(c); cx, cy = (x0 + x1) / 2, (y0 + y1) / 2; w, d = x1 - x0 + 0.02, y1 - y0 + 0.02
        for k in range(10):                                                    # 10 hazard bands over 1.0 m
            b.box((cx, cy, z0 + 0.05 + k * 0.1), (w, d, 0.1), "yel" if k % 2 == 0 else "blk")
        for sx in (-1, 1):
            for sy in (-1, 1):
                b.box((cx + sx * (w / 2 + 0.005), cy + sy * (d / 2 + 0.005), z0 + 0.55), (0.04, 0.04, 1.1), "gal")        # steel corner guards
        b.box((cx, cy, z0 + 1.55), (w + 0.004, d + 0.004, 0.14), "wht")      # a painted band for the level / bay mark
        if i % 2 == 0:                                                          # a cabinet + a hose reel on the face looking at the nearest aisle
            av = min(avs, key=lambda a_: abs(uv(Vector((cx, cy, 0)))[1] - a_)); vdir = 1 if av > uv(Vector((cx, cy, 0)))[1] else -1
            nx_, ny_ = ((0, vdir) if along_x else (vdir, 0)); fx_, fy_ = cx + nx_ * (d / 2 + 0.06 if along_x else w / 2 + 0.06), cy + ny_ * (d / 2 + 0.06 if along_x else w / 2 + 0.06)
            sxz = (0.5, 0.14, 0.7) if along_x else (0.14, 0.5, 0.7)
            b.box((fx_, fy_, z0 + 1.1), sxz, "red"); gx, gy = fx_ + nx_ * 0.075, fy_ + ny_ * 0.075
            b.box((gx, gy, z0 + 1.1), (0.34, 0.012, 0.5) if along_x else (0.012, 0.34, 0.5), "glass")
            b.box((fx_, fy_, z0 + 1.75), (0.35, 0.03, 0.3) if along_x else (0.03, 0.35, 0.3), "grn")                   # a green safety sign
            if i % 4 == 0:
                rx, ry = fx_ + nx_ * 0.0, fy_ + ny_ * 0.0
                b.cyl((rx + (0.55 if along_x else 0), ry + (0 if along_x else 0.55), z0 + 1.2), 0.22, 0.14, "red", axis="y" if along_x else "x"); n_fire += 1
            n_fire += 1
    # --- services along each aisle
    n_trays = n_fans = 0
    for av in avs:
        for sgn in (-1, 1):                                                    # a cable tray on each aisle side
            v = av + sgn * 2.1; z = zc - 0.42
            if along_x:
                b.box(loc(L / 2, v - 0.18, z), (L - 0.6, 0.03, 0.08), "gal", 0); b.box(loc(L / 2, v + 0.18, z), (L - 0.6, 0.03, 0.08), "gal")
            else:
                b.box(loc(L / 2, v - 0.18, z), (0.03, L - 0.6, 0.08), "gal"); b.box(loc(L / 2, v + 0.18, z), (0.03, L - 0.6, 0.08), "gal")
            for u in [0.5 + 0.35 * k for k in range(int((L - 1.0) / 0.35))]:   # rungs
                b.box(loc(u, v, z - 0.03), (0.02, 0.36, 0.02) if along_x else (0.36, 0.02, 0.02), "gal")
            for u in [1.0 + 2.0 * k for k in range(int((L - 2.0) / 2.0))]:      # hangers
                for dv in (-0.18, 0.18):
                    b.box(loc(u, v + dv, (z + zc) / 2), (0.012, 0.012, zc - z), "gal"); 
            n_trays += 1
        for u in (L * 0.3, L * 0.7):                                           # jet fans
            z = zc - 0.95
            ax = "x" if along_x else "y"; c0 = loc(u, av, z)
            b.cyl(c0, 0.27, 1.15, "gal", axis=ax, seg=20); b.cyl(c0 + (Vector((0.62, 0, 0)) if along_x else Vector((0, 0.62, 0))), 0.27, 0.12, "gry", axis=ax, seg=20, rad2=0.33)
            b.cyl(c0 - (Vector((0.62, 0, 0)) if along_x else Vector((0, 0.62, 0))), 0.27, 0.12, "gry", axis=ax, seg=20, rad2=0.33); b.box(c0 + Vector((0, 0, 0.32)), (0.5, 0.25, 0.1) if along_x else (0.25, 0.5, 0.1), "blk")
            for du in (-0.35, 0.35):
                b.box(c0 + (Vector((du, 0, (zc - z) / 2)) if along_x else Vector((0, du, (zc - z) / 2))), (0.02, 0.02, zc - z) if True else (0, 0, 0), "gal"); n_fans += 1
        for u in [1.0 + 2.0 * k for k in range(int((L - 2.0) / 2.0))]:         # straps / hangers on the red sprinkler pipe (parking_ceiling: v = av + 1.0, z = zc - 0.7)
            b.box(loc(u, av + 1.0, zc - 0.7), (0.05, 0.22, 0.04) if along_x else (0.22, 0.05, 0.04), "gry"); b.box(loc(u, av + 1.0, zc - 0.35), (0.012, 0.012, 0.7), "gal")
        for sgn in (-1, 1):                                                    # housings behind the tubes (parking_ceiling: dv = +-1.6, every 3 m from 1.5)
            for u in [1.5 + 3.0 * k for k in range(int((L - 2.5) / 3.0))]:
                b.box(loc(u, av + sgn * 1.6, zc - 0.84), (1.3, 0.12, 0.05) if along_x else (0.12, 1.3, 0.05), "gry")
                for du in (-0.5, 0.5):
                    b.box(loc(u + du, av + sgn * 1.6, zc - 0.42), (0.01, 0.01, 0.84) if True else (0, 0, 0), "blk")
    # --- direction / level boards and equipment
    for av in avs:
        for u in (1.2, L - 1.2):
            z = zc - 1.3
            b.box(loc(u, av, z), (0.06, 1.1, 0.5) if along_x else (1.1, 0.06, 0.5), "blu")
            for dv in (-0.3, 0.0, 0.3):
                b.box(loc(u + 0.035, av + dv, z), (0.01, 0.12, 0.34) if along_x else (0.12, 0.01, 0.34), "wht")
            for dv in (-0.45, 0.45):
                b.box(loc(u, av + dv, (z + zc) / 2 + 0.25), (0.012, 0.012, zc - z - 0.25) if True else (0, 0, 0), "gal")
    if cols:
        c = min(cols, key=lambda o: uv(o.matrix_world.translation)[0]); cx, cy = c.matrix_world.translation.x, c.matrix_world.translation.y
        av = avs[0]; ux, uy = uv(c.matrix_world.translation)
        pay = loc(ux + 2.0, av - 2.7 if uy > av else av + 2.7, fz + 0.7)                                  # a pay station beside the first column
        b.box(pay, (0.45, 0.35, 1.4) if along_x else (0.35, 0.45, 1.4), "gry"); b.box(pay + Vector((0, -0.18 if along_x else 0, 0.2)) if along_x else pay + Vector((-0.18, 0, 0.2)), (0.3, 0.01, 0.25) if along_x else (0.01, 0.3, 0.25), "scr")
        b.box(pay + Vector((0, -0.18 if along_x else 0, -0.1)) if along_x else pay + Vector((-0.18, 0, -0.1)), (0.18, 0.012, 0.03) if along_x else (0.012, 0.18, 0.03), "blk")
        for k in range(2):                                                                                   # two EV chargers
            ev = loc(ux + 6.0 + 2.6 * k, av - 2.7 if uy > av else av + 2.7, fz + 0.65)
            b.box(ev, (0.3, 0.2, 1.3) if along_x else (0.2, 0.3, 1.3), "wht"); b.box(ev + Vector((0, 0, 0.45)), (0.31, 0.21, 0.25) if along_x else (0.21, 0.31, 0.25), "grn"); b.cyl(ev + Vector((0, 0.14 if along_x else 0, -0.1)) if along_x else ev + Vector((0.14, 0, -0.1)), 0.03, 0.5, "blk", axis="z")
            b.box(ev + Vector((0, 0, -0.62)), (0.5, 0.4, 0.06) if along_x else (0.4, 0.5, 0.06), "yel")
    # --- floor: a REAL drain trough (cut into the slab with a boolean, lined, with a slotted galvanised grate), oil stains, tyre marks
    trough = os.environ.get("ROOM_PARKING_TROUGH", "1") == "1"
    fl_obj = parts["floor"]; liner = B({"drain": M["drain"], "wet": M["wet"], "gal": M["gal"]}); n_trough = 0
    for av in avs:
        v = av - 1.2; TW, TD = 0.20, 0.14
        if trough:
            cb = B({"conc": M["conc"]}); cb.box(loc(L / 2, v, fz - TD / 2 + 0.03), (L - 1.0, TW, TD + 0.06) if along_x else (TW, L - 1.0, TD + 0.06), "conc"); cut = cb.make(f"ParkingFixtures(cutter {av:.1f})")
            cut.display_type = "WIRE"; cut.hide_render = True; cut.hide_viewport = True
            md = fl_obj.modifiers.new("ir_trough", "BOOLEAN"); md.operation = "DIFFERENCE"; md.object = cut; md.solver = "FAST"
            ln = (L - 1.0) if True else 0
            liner.box(loc(L / 2, v, fz - TD), (ln, TW, 0.01) if along_x else (TW, ln, 0.01), "wet")                                         # the bottom, a wet film
            for sg in (-1, 1):
                liner.box(loc(L / 2, v + sg * TW / 2, fz - TD / 2), (ln, 0.01, TD) if along_x else (0.01, ln, TD), "drain")                  # the walls
            for sg in (-1, 1):
                liner.box(loc(L / 2 + sg * ln / 2, v, fz - TD / 2), (0.01, TW, TD) if along_x else (TW, 0.01, TD), "drain")                    # the ends
            for sg in (-1, 1):
                liner.box(loc(L / 2, v + sg * (TW / 2 + 0.012), fz + 0.004), (ln, 0.024, 0.012) if along_x else (0.024, ln, 0.012), "gal")    # the angle-iron frame rails
        for u in [0.8 + 0.015 * k for k in range(int((L - 1.6) / 0.015))]:                                                                  # grate bars 5 mm, gaps 10 mm
            liner.box(loc(u, v, fz + 0.006), (0.005, TW - 0.01, 0.012) if along_x else (TW - 0.01, 0.005, 0.012), "gal")
        n_trough += 1
        for k in range(5):                                                                                                                  # a water / grease stain fanning out from the grate edge
            u0 = rng.uniform(1.5, L - 1.5); dv = rng.choice((-1, 1)) * rng.uniform(0.3, 0.9)
            r = bmesh.ops.create_cone(b.bm, cap_ends=True, segments=16, radius1=rng.uniform(0.25, 0.7), radius2=rng.uniform(0.25, 0.7), depth=0.002)
            bmesh.ops.scale(b.bm, vec=(2.0, 0.7, 1.0) if along_x else (0.7, 2.0, 1.0), verts=r["verts"]); bmesh.ops.translate(b.bm, vec=tuple(loc(u0, v + dv, fz + 0.002)), verts=r["verts"]); b._slot("oil", r["verts"])
        for k in range(2):                                                                                    # tyre marks in the aisle
            u0 = rng.uniform(3, L - 8); b.box(loc(u0 + 2.5, av + rng.uniform(-1.8, 1.8), fz + 0.0015), (5.0, 0.18, 0.003) if along_x else (0.18, 5.0, 0.003), "tyre", yaw=rng.uniform(-0.05, 0.05))
    cars = [o for o in bpy.data.objects if o.type == "MESH" and o.parent is None and o.name.startswith("ParkedCarFactory")]
    for o in cars:
        if rng.random() < 0.4:
            x0, x1, y0, y1, z0, z1 = _bbox(o); r = bmesh.ops.create_cone(b.bm, cap_ends=True, segments=14, radius1=rng.uniform(0.2, 0.4), radius2=rng.uniform(0.2, 0.4), depth=0.003)
            bmesh.ops.scale(b.bm, vec=(1.0, rng.uniform(0.6, 1.0), 1.0), verts=r["verts"]); bmesh.ops.translate(b.bm, vec=((x0 + x1) / 2 + rng.uniform(-0.6, 0.6), (y0 + y1) / 2 + rng.uniform(-0.6, 0.6), z0 + 0.003), verts=r["verts"]); b._slot("oil", r["verts"])
    o_main = b.make(f"ParkingFixtures({name})")
    if trough:
        liner.make(f"ParkingFixtures(trough {name})")
    # --- windows plugged (a car park has none)
    nwin = 0
    for o in list(bpy.data.objects):
        if o.name.startswith(("EnvWindowCard", "EnvWindowGround")):
            bpy.data.objects.remove(o, do_unlink=True)
        elif o.name.startswith(("window", "WindowFactory")) and o.type == "MESH" and (o.parent is None or (o.name.startswith("WindowFactory") and not o.parent.name.startswith(("window", "WindowFactory")))):   # one plug per opening: a WindowFactory under a plugged window made a coincident 2nd box -> rendered black (S28F r15-r19)
            x0, x1, y0, y1, z0, z1 = _bbox(o); t = o.matrix_world.translation
            if os.environ.get("ROOM_PARKING_ALLWIN") == "1" or (fx0 - 1.0 <= t.x <= fx1 + 1.0 and fy0 - 1.0 <= t.y <= fy1 + 1.0):         # ALLWIN: underground, every window of the building (the lobby hallway kept one, S28F r9)
                pb = B({"conc": M["conc"]}); pb.box(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2), (max(x1 - x0, 0.3), max(y1 - y0, 0.3), z1 - z0 + 0.02), "conc"); pb.make("ParkingFixtures(windowplug)")
                for ch in o.children_recursive:
                    ch.hide_render = True; ch.hide_viewport = True
                o.hide_render = True; nwin += 1
    # --- lobby: white drop ceiling, no hanger rods
    nl = 0
    for n_, p_ in rooms.items():
        if n_ == name or "floor" not in p_ or "wall" not in p_ or not n_.startswith("hallway"):
            continue
        x0, x1, y0, y1, z0, z1 = _bbox(p_["floor"]); zw = _bbox(p_["wall"])[5]
        for o in list(bpy.data.objects):
            t = o.matrix_world.translation
            if x0 - 0.1 <= t.x <= x1 + 0.1 and y0 - 0.1 <= t.y <= y1 + 0.1 and o.name.split("(")[0] in ("HighBayCordFactory", "RoofGirderFactory", "RoofDeckFactory", "HighBayLampFactory"):
                bpy.data.objects.remove(o, do_unlink=True)
        lb = B({"ceil": M["ceil"]}); lb.box(((x0 + x1) / 2, (y0 + y1) / 2, zw - 0.12), (x1 - x0, y1 - y0, 0.03), "ceil"); lb.make(f"ParkingFixtures(lobbyceiling {n_})"); nl += 1
        if os.environ.get("ROOM_LOBBY_WHITE") == "1":                                  # S28F r12: the lobby ref has a finished white ceiling: the car-park beams / ducts / pipes hanging below the drop ceiling inside the lobby go
            for po_ in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("ParkingCeilingFactory", "RoofGirderFactory"))]:
                bm_ = bmesh.new(); bm_.from_mesh(po_.data); mw_ = po_.matrix_world
                dead_ = [f_ for f_ in bm_.faces if x0 - 0.1 <= (mw_ @ f_.calc_center_median()).x <= x1 + 0.1 and y0 - 0.1 <= (mw_ @ f_.calc_center_median()).y <= y1 + 0.1 and (mw_ @ f_.calc_center_median()).z < zw - 0.1]
                if dead_:
                    bmesh.ops.delete(bm_, geom=dead_, context="FACES"); bm_.to_mesh(po_.data)
                bm_.free()
        if os.environ.get("ROOM_LOBBY_WHITE") == "1":                                  # S28F r10: the elevator lobby ref is smooth white paint, not mottled concrete
            wm_ = pa._flat("ir_lobby_white", (0.86, 0.86, 0.84), 0.55); wm_["weathered"] = True
            for k_ in (".wall", ".exterior"):
                wo_ = bpy.data.objects.get(n_ + k_)
                if wo_ is not None:
                    for sl_ in wo_.material_slots:
                        sl_.material = wm_
    stats["parking_fixtures"] = {"troughs": n_trough, "room": name, "columns": len(cols), "fire": n_fire, "trays": n_trays, "fans": n_fans, "windows_plugged": nwin, "lobby_ceilings": nl}
    return 1
