"""Office-floor props for the O3 / O4 / O5 floors (user 2026-10-22): bench desk with a planter divider, white cafe island, patterned pouf, wire stool, globe pendant.

    DeskBenchFactory    two rows of N desks back to back (N = class attr, layout 'seats'), a planter trough with leafy plants down the spine, pedestals, one monitor per desk; obj['seats'] feeds
                        RoomRealizer._pod_chairs. Front +X (the +x row), 1.2 m per seat, 1.5 m across.
    WhiteIslandFactory  a long cafe / kitchen island (PL x PD, class attrs): white stone top with a stool-side overhang, oak slat front, a handle-less white back with a sink and open oak shelves behind.
    PoufFactory         a round pouf in a printed fabric (2-3 coloured bands), STYLE pouf_rgb = [[r,g,b], ...].
    WireStoolFactory    a bar stool of black (STYLE wire_stool_rgb) round wire: a ring seat, four legs, two rings.
    GlobePendantFactory a white opal globe on a black cord (origin at the ceiling mount, hangs down), a faint point light.
STYLE keys (kit): desk_top_rgb (oak), planter_leaf_rgb, island_front_rgb."""
from __future__ import annotations

import math
import os
import random

import bpy

from room_planner import proc_assets as pa
from room_planner import proc_boutique_flagship as fl


def _leaf(i, r, rgb):
    m = pa._flat(f"ir_off_leaf_{int(rgb[1] * 100)}", rgb, 0.7)
    return m


class DeskBenchFactory:
    N = 4

    def __init__(self, seed):
        self.r = random.Random(seed)
        self.top = tuple(pa.STYLE.get("desk_top_rgb") or (0.62, 0.46, 0.3)); self.leaf = tuple(pa.STYLE.get("planter_leaf_rgb") or (0.16, 0.38, 0.14))

    def spawn_asset(self, i):
        r, n, w, d = self.r, self.N, 1.2, 0.7
        L = n * w
        top = pa._flat(f"ir_bench_top_{int(self.top[0] * 100)}_{int(self.top[2] * 100)}", self.top, 0.5); steel = pa._flat("ir_desk_frame", (0.75, 0.75, 0.76), 0.35, 0.8)
        black = pa._flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0); ped = pa._flat("ir_pedestal", (0.5, 0.5, 0.52), 0.4, 0.3)
        pot = pa._flat("ir_bench_trough", (0.1, 0.1, 0.1), 0.6); leaf = _leaf(i, r, self.leaf); leaf2 = _leaf(i, r, tuple(c * 0.75 for c in self.leaf))
        stem = pa._flat("ir_bench_stem", (0.2, 0.3, 0.12), 0.7)
        R0 = (0, 0, 0)
        tops, legs, peds, mons, plants, plants2, stems = [], [], [], [], [], [], []
        seats = []
        for side in (1, -1):
            for k in range(n):
                y = -L / 2 + (k + 0.5) * w; x = side * (d / 2 + 0.01 + 0.12)
                tops.append(("box", (x, y, 0.735), (d, w - 0.01, 0.03), R0))
                peds.append(("box", (x - side * 0.05, y + w / 2 - 0.25, 0.3), (0.55, 0.4, 0.58), R0))
                mons.append(("box", (side * 0.34, y, 1.0), (0.02, 0.56, 0.34), R0)); mons.append(("box", (side * 0.34, y, 0.85), (0.03, 0.04, 0.2), R0))
                seats.append((side * (d + 0.55), y, math.atan2(0, -side)))
        for sx in (1, -1):
            for yy in (-L / 2 + 0.03, L / 2 - 0.03):
                legs.append(("box", (sx * (d / 2 + 0.13), yy, 0.36), (d - 0.05, 0.04, 0.72), R0))
        legs.append(("box", (0, 0, 0.6), (0.18, L - 0.1, 0.05), R0))
        potb = [("box", (0, 0, 0.8), (0.26, L - 0.12, 0.17), R0)]
        m = max(2, int(L / 0.55))
        hssd_ = pa.STYLE.get("floor_plant_style") == "hssd" and not os.environ.get("ROOM_BENCH_CARD_PLANTS")      # the kit's plants are HSSD scans: no card-leaf plants in the planter bar either
        for k in range(0 if hssd_ else m):                          # one leafy plant per ~0.55 m: a short stem and 8-10 pointed leaves radiating and arching, two greens
            yb = -L / 2 + 0.25 + (k + 0.5) * (L - 0.5) / m; hz = r.uniform(0.2, 0.34)
            stems.append(("cyl", (0, yb, 0.885 + hz * 0.25), (0.012, 0.009, hz * 0.5), R0))
            for q in range(r.randint(8, 10)):
                az = q * 2 * math.pi / 9 + r.uniform(-0.3, 0.3); tilt = r.uniform(0.35, 1.15); ln = hz * r.uniform(0.7, 1.15)
                c = (math.sin(tilt) * math.cos(az) * ln * 0.55, yb + math.sin(tilt) * math.sin(az) * ln * 0.55, 0.9 + hz * 0.45 + math.cos(tilt) * ln * 0.55)
                (plants if q % 2 == 0 else plants2).append(("lsph", c, (0.012, 0.045, ln * 0.55), (0.0, tilt, az)))
        o = pa._prims(f"DeskBenchFactory({i}).spawn_asset({i})", [(top, tops), (steel, legs), (ped, peds), (black, mons), (pot, potb), (stem, stems), (leaf, plants), (leaf2, plants2)])
        o["seats"] = [list(s) for s in seats]
        if hssd_:                                                    # O4: 1 HSSD scanned potted plant per ~1.2 m of planter bar, 0.55-0.85 m tall, linked copies parented to the bench (shared mesh data)
            try:
                import sys as _sys
                if "/jarvis/project/robomituba/tools/infinigen" not in _sys.path:
                    _sys.path.insert(0, "/jarvis/project/robomituba/tools/infinigen")
                import abo_assets, asset_pools
                from mathutils import Matrix as _M
                pool_ = [e_ for e_ in asset_pools.pool("tall_plant") if e_["triangles"] <= 36000 and "banana" not in e_["name"].lower() and e_["extent_m"][1] <= 2.0]
                for k in range(max(2, int(L / 1.2))):
                    e_ = abo_assets.pick(r, pool_); po = abo_assets._import(e_, f"BenchHssdPlant{i}_{k}")
                    if not po.data.get("ir_base0"):
                        zs_ = [v_.co.z for v_ in po.data.vertices]; xs_ = [v_.co.x for v_ in po.data.vertices]; ys_ = [v_.co.y for v_ in po.data.vertices]
                        po.data.transform(_M.Translation((-(min(xs_) + max(xs_)) / 2, -(min(ys_) + max(ys_)) / 2, -min(zs_)))); po.data["ir_base0"] = 1
                    hz_ = max(v_.co.z for v_ in po.data.vertices); kk = r.uniform(0.55, 0.85) / max(hz_, 0.3); po.scale = (kk, kk, kk); po.rotation_euler = (0, 0, r.uniform(0, 6.28))
                    po.parent = o; po.matrix_parent_inverse = _M.Identity(4); po.location = (0.0, -L / 2 + 0.3 + (k + 0.5) * (L - 0.6) / max(2, int(L / 1.2)), 0.885)
            except Exception as ex_:                                 # noqa: BLE001 -- a bench without plants is better than a failed round
                print(f"[bench] hssd plants skipped: {ex_!r}"[:140], flush=True)
        return o


class WhiteIslandFactory:
    PL, PD = 4.0, 1.0

    def __init__(self, seed):
        self.front = tuple(pa.STYLE.get("island_front_rgb") or (0.7, 0.55, 0.36))

    def spawn_asset(self, i):
        L, D = self.PL, self.PD
        stone = pa._flat("ir_island_white", (0.93, 0.93, 0.91), 0.25); oak = pa._flat(f"ir_island_oak_{int(self.front[0] * 100)}", self.front, 0.5)
        white = pa._flat("ir_island_body_white", (0.9, 0.9, 0.88), 0.45); steel = pa._flat("ir_island_steel", (0.75, 0.75, 0.78), 0.2, 1.0)
        slats = [("box", D / 2 - 0.02, -L / 2 + 0.05 + k * 0.1, 0.45, 0.03, 0.06, 0.88) for k in range(int((L - 0.1) / 0.1))]       # oak slats on the stool (+X) side
        body = [("box", -0.05, 0, 0.45, D - 0.14, L - 0.02, 0.86)]
        topb = [("box", 0.04, 0, 0.9, D + 0.1, L + 0.04, 0.05)]                                                                       # 0.1 m overhang on the +X (stool) side
        sink = [("box", -0.18, -L / 4, 0.925, 0.4, 0.5, 0.01), ("cyl", (-0.18, -L / 4 + 0.15, 0.95), (-0.18, -L / 4 + 0.15, 1.2), 0.012, 8), ("cyl", (-0.18, -L / 4 + 0.15, 1.2), (-0.1, -L / 4 + 0.15, 1.2), 0.012, 8)]
        return fl.mesh_object(f"WhiteIslandFactory({i}).spawn_asset({i})", [(stone, topb), (white, body), (oak, slats), (steel, sink)])


class PoufFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)
        pal = pa.STYLE.get("pouf_rgb") or [(0.85, 0.35, 0.3), (0.2, 0.45, 0.6), (0.95, 0.8, 0.3), (0.9, 0.88, 0.82)]
        self.c = [tuple(c) for c in self.r.sample(list(pal), min(3, len(pal)))]; self.rad = self.r.uniform(0.26, 0.34)

    def spawn_asset(self, i):
        rad, h = self.rad, self.r.uniform(0.38, 0.46)
        groups = []
        for k, c in enumerate(self.c):
            groups.append((pa._flat(f"ir_pouf_{int(c[0] * 100)}_{int(c[1] * 100)}_{int(c[2] * 100)}", c, 0.85), [("cyl", (0, 0, h * k / len(self.c) + 0.01), (0, 0, h * (k + 1) / len(self.c) + 0.01), rad - 0.01 * k, 24)]))
        groups[0][1].append(("sph", (0, 0, h), rad * 0.55, 2))
        return fl.mesh_object(f"PoufFactory({i}).spawn_asset({i})", groups, bevel=False)


class WireStoolFactory:
    def __init__(self, seed):
        self.c = tuple(pa.STYLE.get("wire_stool_rgb") or (0.04, 0.04, 0.045))

    def spawn_asset(self, i):
        m = pa._flat(f"ir_wire_{int(self.c[0] * 100)}_{int(self.c[1] * 100)}", self.c, 0.45, 0.8)
        H, R = 0.66, 0.19
        parts = []
        for k in range(4):
            a = math.pi / 4 + k * math.pi / 2
            parts.append(("cyl", (R * 1.15 * math.cos(a), R * 1.15 * math.sin(a), 0.0), (R * 0.9 * math.cos(a), R * 0.9 * math.sin(a), H), 0.007, 6))
        for z, rr in ((0.24, R * 1.05), (H, R * 0.9)):                 # two wire rings (polygon of thin cylinders) + the seat ring
            for k in range(12):
                a0, a1 = 2 * math.pi * k / 12, 2 * math.pi * (k + 1) / 12
                parts.append(("cyl", (rr * math.cos(a0), rr * math.sin(a0), z), (rr * math.cos(a1), rr * math.sin(a1), z), 0.006, 5))
        for k in range(6):                                              # seat wires across the top
            y = -R * 0.8 + k * R * 1.6 / 5; hx = math.sqrt(max(R * R * 0.8 - y * y, 0.0))
            parts.append(("cyl", (-hx, y, H), (hx, y, H), 0.005, 5))
        return fl.mesh_object(f"WireStoolFactory({i}).spawn_asset({i})", [(m, parts)], bevel=False)


class GlobePendantFactory:
    def __init__(self, seed):
        self.rad = random.Random(seed).choice((0.16, 0.2, 0.25))

    def spawn_asset(self, i):
        glow = pa._flat("ir_globe_opal", (0.96, 0.95, 0.9), 0.3); gb = glow.node_tree.nodes["Principled BSDF"]
        gb.inputs["Emission Color"].default_value = (1.0, 0.95, 0.85, 1); gb.inputs["Emission Strength"].default_value = 3.0
        cord = pa._flat("ir_pend_cord", (0.05, 0.05, 0.05), 0.5)
        drop = 0.9
        o = fl.mesh_object(f"GlobePendantFactory({i}).spawn_asset({i})", [(cord, [("cyl", (0, 0, -drop), (0, 0, 0), 0.004, 6)]), (glow, [("sph", (0, 0, -drop - self.rad), self.rad, 3)])], bevel=False)
        ld = bpy.data.lights.new(f"ir_globe_{i}", "POINT"); ld.energy = 30.0; ld.color = (1.0, 0.93, 0.8); ld.shadow_soft_size = self.rad
        lo = bpy.data.objects.new(f"PointLampFactory(globe).spawn_asset({i})", ld); bpy.context.scene.collection.objects.link(lo); lo.parent = o; lo.location = (0, 0, -drop - self.rad)
        return o


class AccentArmchairFactory:
    """Hotel accent armchair (front +X, 0.8 x 0.8 m): a rounded tub chair in the room's accent colour: a plump seat cushion, a reclined rounded back, softly rolled arms and four tapered, splayed oak legs.
    rgb is set by realize from kit STYLE armchair_rgb_by_room."""
    rgb = None

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        c = tuple(self.rgb or (0.5, 0.5, 0.5))
        fab = pa._flat("ir_acc_arm_%d_%d_%d" % (int(c[0] * 100), int(c[1] * 100), int(c[2] * 100)), c, 0.9); oak = pa._flat("ir_acc_oak", (0.55, 0.4, 0.26), 0.5, wood=True)
        seam = pa._flat("ir_acc_seam", tuple(v * 0.55 for v in c), 0.9)
        body = [("rbox", (0.0, 0, 0.3), (0.66, 0.72, 0.14), (0, 0, 0)),                         # base
                ("rbox", (0.03, 0, 0.41), (0.56, 0.58, 0.14), (0, 0, 0)),                        # seat cushion
                ("rbox", (-0.27, 0, 0.62), (0.18, 0.7, 0.52), (0, -0.2, 0))]                       # reclined back
        body += [("rbox", (-0.02, sy * 0.33, 0.5), (0.58, 0.14, 0.26), (0, 0, 0)) for sy in (1, -1)]       # rolled arms
        seams = [("box", (0.03, 0, 0.485), (0.56, 0.006, 0.006), (0, 0, 0)), ("box", (0.31, 0, 0.41), (0.006, 0.58, 0.006), (0, 0, 0))]
        legs = [("cyl", (lx * 0.27, ly * 0.28, 0.115), (0.012, 0.024, 0.23), (-ly * 0.12, lx * 0.12, 0)) for lx in (1, -1) for ly in (1, -1)]
        return pa._prims(f"AccentArmchairFactory({i}).spawn_asset({i})", [(fab, body), (seam, seams), (oak, legs)])


class LoveseatFactory:
    """Hotel loveseat (front +X, 1.5 x 0.8 m): two plump seat cushions, a low rounded back and rolled arms in the room's accent colour on tapered oak legs (kit STYLE sofa_rgb_by_room)."""
    rgb = None

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        c = tuple(self.rgb or (0.5, 0.5, 0.5))
        fab = pa._flat("ir_loveseat_%d_%d_%d" % (int(c[0] * 100), int(c[1] * 100), int(c[2] * 100)), c, 0.9); oak = pa._flat("ir_acc_oak", (0.55, 0.4, 0.26), 0.5, wood=True)
        seam = pa._flat("ir_acc_seam", tuple(v * 0.55 for v in c), 0.9)
        body = [("rbox", (0.0, 0, 0.3), (0.72, 1.46, 0.14), (0, 0, 0))]
        body += [("rbox", (0.05, sy * 0.35, 0.42), (0.6, 0.66, 0.15), (0, 0, 0)) for sy in (1, -1)]
        body += [("rbox", (-0.29, 0, 0.6), (0.18, 1.46, 0.5), (0, -0.18, 0))]
        body += [("rbox", (0.0, sy * 0.72, 0.48), (0.7, 0.16, 0.3), (0, 0, 0)) for sy in (1, -1)]
        seams = [("box", (0.05, 0, 0.5), (0.6, 0.006, 0.006), (0, 0, 0))]
        legs = [("cyl", (lx * 0.3, ly * 0.66, 0.11), (0.012, 0.024, 0.22), (-ly * 0.1, lx * 0.1, 0)) for lx in (1, -1) for ly in (1, -1)]
        return pa._prims(f"LoveseatFactory({i}).spawn_asset({i})", [(fab, body), (seam, seams), (oak, legs)])


class LuggageRackFactory:
    """Hotel luggage rack (front +X, 0.7 x 0.45 x 0.5 m): an oak frame of two X-legs with three woven black straps; the open top at 0.48 m."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        oak = pa._flat("ir_acc_oak", (0.55, 0.4, 0.26), 0.5, wood=True); strap = pa._flat("ir_lug_strap", (0.12, 0.1, 0.09), 0.8)
        L, D = 0.7, 0.45
        parts = []
        for sy in (1, -1):
            parts += [("box", 0.0, sy * (L / 2 - 0.03), 0.47, D, 0.035, 0.035), ("box", 0.0, sy * (L / 2 - 0.03), 0.04, D - 0.06, 0.035, 0.035)]
        legs = [("cyl", (sx * (D / 2 - 0.04), sy * (L / 2 - 0.03), 0.0), (sx * (D / 2 - 0.04), sy * (L / 2 - 0.03), 0.5), 0.014, 6) for sx in (1, -1) for sy in (1, -1)]
        straps = [("box", x, 0.0, 0.485, 0.05, L - 0.06, 0.012) for x in (-0.14, 0.0, 0.14)]
        return fl.mesh_object(f"LuggageRackFactory({i}).spawn_asset({i})", [(oak, parts + legs), (strap, straps)], bevel=False)


def atrium_planting(r, L, D, H, hmax=None):
    """Tall, layered indoor planting for the atrium planter (kit atrium_big_plants): a fiddle-leaf fig tree (2.8-3.4 m), a multi-stem areca palm with pinnate fronds (2.3-3.0 m), a monstera clump and a low
    under-planting of fern fronds, all with card-thin textured leaves (proc_leaf.py). Planter-local frame: x depth, y along the length, z up from the planter's floor H.
    Returns ([(material, stem cylinders)], leaves object): the caller joins the leaves object into the planter (pa._join_cloth)."""
    from room_planner import proc_leaf as pl
    bark = pa._flat("ir_atr_bark", (0.14, 0.09, 0.055), 0.8)
    mt = pl.mats(); lv = pl.Leaves(r.randrange(1 << 20)); stems = []; zb = H + 0.02
    hmax = hmax or 3.6                                                            # the room's usable height (kit atrium_tree_max_m): the fig's crown and the palm's fronds stay under it
    pl.fig(lv, stems, mt, r, 0.0, -L / 2 + 0.6, zb, min(r.uniform(2.8, 3.4), hmax - zb - 0.5))
    pl.palm(lv, stems, mt, r, 0.0, r.uniform(-0.1, 0.4), zb, r.randint(5, 7), 2.3, max(2.0, min(3.0, hmax - zb - 0.8)))
    pl.monstera(lv, stems, mt, r, 0.05, L / 2 - 0.6, zb, r.randint(8, 11))
    pl.ferns(lv, mt, r, 0.0, 0.0, zb, 22, D / 2 - 0.12, L / 2 - 0.15)
    lo = lv.object("AtriumLeaves"); lo.location = (D / 2, 0.0, 0.0)                         # the planter's back is at x = 0: centre the planting on its depth
    return [(bark, [(kd, (c[0] + D / 2, c[1], c[2]), sz, rot) for kd, c, sz, rot in stems])], lo


class PottedPlantFactory:
    """A potted indoor plant for floors and corners (kit floor_plant_style = fig | palm | monstera | ficus | mix): ~1.2-1.7 m tall in a 0.34 m ceramic pot, with card-thin textured leaves from proc_leaf.py (fig: big
    glossy leaves on branches; palm: pinnate fronds of many narrow leaflets; monstera: broad leaves on arching petioles; ficus: a dense crown of small leaves). Front +X, origin at the pot's base."""

    def __init__(self, seed):
        self.r = random.Random(seed)
        st = pa.STYLE.get("floor_plant_style") or "mix"
        self.kind = self.r.choice(("fig", "palm", "monstera", "ficus")) if st == "mix" else st

    def spawn_asset(self, i):
        from room_planner import proc_leaf as pl
        r, kind = self.r, self.kind
        pot = pa._flat("ir_pp_pot", r.choice(((0.82, 0.8, 0.74), (0.45, 0.3, 0.22), (0.12, 0.12, 0.13), (0.75, 0.76, 0.72))), 0.7)
        soil = pa._flat("ir_pp_soil", (0.05, 0.035, 0.025), 0.9); bark = pa._flat("ir_atr_bark", (0.14, 0.09, 0.055), 0.8)
        mt = pl.mats(); lv = pl.Leaves(r.randrange(1 << 20)); stems = []; zb = 0.36
        if kind == "fig":
            pl.fig(lv, stems, mt, r, 0.0, 0.0, zb, r.uniform(0.9, 1.25), sc=0.55)
        elif kind == "palm":
            pl.palm(lv, stems, mt, r, 0.0, 0.0, zb, r.randint(4, 6), 0.95, 1.4, sc=0.5)
        elif kind == "monstera":
            pl.monstera(lv, stems, mt, r, 0.0, 0.0, zb, r.randint(8, 11), sc=0.75)
        else:
            pl.ficus(lv, stems, mt, r, 0.0, 0.0, zb, r.uniform(0.75, 1.05), sc=0.7)
        R0 = (0, 0, 0)
        o = pa._prims(f"PottedPlantFactory({i}).spawn_asset({i})", [(pot, [("cyl", (0, 0, 0.17), (0.15, 0.2, 0.34), R0)]), (soil, [("cyl", (0, 0, 0.345), (0.185, 0.185, 0.02), R0)]), (bark, stems)])
        return pa._join_cloth(o, [lv.object(f"PottedLeaves({i})")])


from room_planner.proc_chiller import OpenChillerFactory  # noqa: E402,F401  (the open-front multideck chiller lives in proc_chiller.py; this keeps proc:OpenChillerFactory resolvable through PROP_MODULES)
