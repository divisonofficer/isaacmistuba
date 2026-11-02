"""Furnish Infinigen apartment rooms so they read as lived in, not as a finishes showroom (user 2026-10-15: "인테리어모델하우스같다").

Infinigen's apartment rooms are 20-50 m^2 with a handful of anchors each (a bed and a lamp; a dining table with one or two chairs), so
most of every floor is bare. This adds, on free floor only:

  ceilings     matte off-white plaster (vanilla keeps Infinigen 1.x's random-colour ceilings: purple rooms)
  dining-room  copies of the room's own chair model around the table, up to its length (4-6), facing it
  living-room  sofa on the longest free wall, coffee table 0.45 m in front, rug under both, armchair at its side, side table and
               floor lamp at the sofa ends, a few things on the coffee table
  bedroom      a nightstand on each side of the bed head, a dresser on a free wall, a rug at the foot

Furniture is ABO product models (abo_assets); ABO seating faces -Y after import (backrest at +Y, measured on 8 sofas/chairs),
Infinigen's faces +X. Every placement must stand on the room's own floor, clear of other objects' footprints by 5 cm, and keep 0.9 m
in front of doors free.
"""
from __future__ import annotations

import math
import re

import bpy
from mathutils import Matrix, Vector

import abo_assets as abo
import room_dressing as rd

DOOR_CLEAR_M = 0.9


def _pool(types, *, w=(0, 9), d=(0, 9), h=(0, 9), name=None):
    """ABO entries by product type and size (glTF extent: x width, y height, z depth)."""
    out = []
    for e in abo.entries():
        if e["product_type"] not in types or e["triangles"] > abo.MAX_TRIANGLES or e.get("emissive_materials"):
            continue
        x, y, z = e["extent_m"]
        if w[0] <= x <= w[1] and d[0] <= z <= d[1] and h[0] <= y <= h[1] and (name is None or name(e)):
            out.append(e)
    return out


POOLS = {}


def pool(key):
    if not POOLS:
        POOLS.update(
            sofa=_pool(("SOFA",), w=(1.6, 2.4), d=(0.75, 1.1), h=(0.65, 1.0)),
            coffee=_pool(("TABLE",), w=(0.6, 1.4), d=(0.4, 0.9), h=(0.3, 0.55)),
            side=_pool(("TABLE",), w=(0.35, 0.65), d=(0.35, 0.65), h=(0.45, 0.72)),
            armchair=_pool(("CHAIR", "SOFA"), w=(0.65, 1.05), d=(0.65, 1.0), h=(0.7, 1.1)),
            floorlamp=_pool(("LAMP",), w=(0.2, 0.7), d=(0.2, 0.7), h=(1.2, 1.9)),
            rug=_pool(("RUG",), w=(1.4, 2.6), d=(1.0, 2.0), h=(0.0, 0.05)),
            nightstand=_pool(("TABLE", "CABINET", "DRESSER"), w=(0.35, 0.65), d=(0.3, 0.55), h=(0.45, 0.75)),
            dresser=_pool(("DRESSER", "CABINET"), w=(0.8, 1.6), d=(0.35, 0.6), h=(0.7, 1.3)),
            rack=_pool(("STORAGE_RACK",), h=(1.4, 2.4)) or _pool(("SHELF",), w=(0.8, 2.0), h=(1.5, 2.4)),
            ladder=_pool(("LADDER", "TOOLS"), h=(1.2, 2.2)),
            stool=_pool(("STOOL_SEATING",), h=(0.45, 0.85)),
            cart=_pool(("UTILITY_CART_WAGON",)) or _pool(("STORAGE_RACK",), h=(0.6, 1.2)),
            fan=_pool(("ELECTRIC_FAN",), h=(0.25, 1.6)),
            conftable=_pool(("TABLE",), w=(1.6, 3.2), d=(0.8, 1.4), h=(0.68, 0.8)),
            desk=_pool(("DESK",), w=(0.9, 1.9), h=(0.68, 0.82)),
            # task chairs: a seat-sized footprint and no recliners -- a 1.1 m executive recliner blocked every pod seat and filled the
            # meeting room with lounge chairs (2026-10-16)
            officechair=_pool(("CHAIR",), w=(0.5, 0.72), d=(0.5, 0.75), h=(0.85, 1.3), name=lambda e: bool(re.search(
                r"office|desk|task|swivel|mesh|ergonomic|conference|办公|오피스|사무|bureau|schreibtisch", e["name"] + " " + " ".join(e.get("keywords") or []), re.I))
                and not re.search(r"reclin|massage|gaming|lounge|big and tall|executive|躺|리클라이너|sled|cantilever|visitor|guest|"
                                  r"stack|reception|waiting|leather|stool|drafting|counter height|bar height|tub|lounge|accent|club|armchair|"
                                  r"레이싱|게임|racing|sportivo|赛车|游戏|dining|餐椅|다이닝|comedor|patas de madera|Ravenna|凳|스툴|vanity|spa|"
                                  r"皮革|가죽|이그제큐티브|行政|客座|接待|宾客|direzionale|벨벳|天鹅绒|velvet|Rivet|Stone & Beam|리벳|Movian|Dubna|Arendsee|schienale alto", e["name"], re.I)),   # critic r2/r4;
            # the multilingual names hid racing chairs from the English 'gaming' test: floor A2 r17 filled the open office with red/black
            # 'internet-cafe' chairs (user 2026-10-17); 'leather' stays out, so executive and guest chairs do not appear
            bookcase=_pool(("SHELF",), w=(0.6, 1.3), h=(1.4, 2.2), name=lambda e: not re.search(r"ladder|leaning|A-frame", e["name"], re.I)),   # critic r2/r3
            counter=_pool(("CABINET", "DRESSER", "HOME_FURNITURE_AND_DECOR"), w=(1.2, 2.4), h=(0.85, 1.15)),
            cafetable=_pool(("TABLE",), w=(0.5, 1.2), d=(0.5, 1.2), h=(0.68, 0.8)),
            # dining-type chairs only: the height-only filter let accent/arm chairs in and every cafe read as a lounge (2026-10-16)
            cafechair=_pool(("CHAIR",), w=(0, 0.62), h=(0.75, 1.0), name=lambda e: bool(re.search(
                r"dining|bistro|side chair|cafe|café|kitchen|餐椅|餐厅|다이닝|식탁|chaise de salle|esszimmer|sedia da pranzo|silla de comedor",
                e["name"] + " " + " ".join(e.get("keywords") or []), re.I))),
            barstool=_pool(("STOOL_SEATING",), h=(0.6, 1.05), name=lambda e: not re.search(
                r"rustic|farmhouse|solid wood|wooden|reclaimed|vintage", e["name"], re.I)),   # critic r4: red wooden stools read as a home bar
            board=_pool(("WRITING_BOARD",)) or _pool(("PINBOARD",)),
            filing=_pool(("CABINET", "STORAGE_DRAWER"), w=(0.35, 0.9), h=(0.6, 1.4), name=lambda e: not re.search(
                r"rustic|reclaimed|pallet|farmhouse|vintage|distressed|barn|shabby|nightstand|bedside|night stand", e["name"], re.I)),   # critic r2/r3: pallet-wood cabinet, nightstand
        )
    return POOLS[key]


class AboPick:
    """An ABO model by seed from one pool, Infinigen-factory shaped for room_dressing/activity spawners."""
    def __init__(self, key, rng):
        self.key, self.entry = key, abo.pick(rng, pool(key))

    def spawn(self, i):
        o = abo._import(self.entry, f"Abo{self.key.title()}Factory({self.entry['id']}).spawn_asset({i})")
        bpy.context.view_layer.update()
        return o


# ---- geometry ----------------------------------------------------------------------------------------------------------------------
def footprint(o):
    """World xy box of o and its children."""
    pts = [x.matrix_world @ Vector(c) for x in [o, *o.children_recursive] if x.type == "MESH" for c in x.bound_box] \
        or [o.matrix_world.translation]
    return (min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts),
            min(p.z for p in pts), max(p.z for p in pts))


def _overlap(a, b, m=0.05):
    return a[0] < b[1] + m and b[0] < a[1] + m and a[2] < b[3] + m and b[2] < a[3] + m


class Room:
    def __init__(self, name, parts, scene, deps):
        self.name, self.type = name, name.split("_")[0]
        self.floor, self.wall = parts["floor"], parts.get("wall")
        self.scene, self.deps = scene, deps
        bb = [self.floor.matrix_world @ Vector(c) for c in self.floor.bound_box]
        self.z = max(p.z for p in bb)
        self.box = (min(p.x for p in bb), max(p.x for p in bb), min(p.y for p in bb), max(p.y for p in bb))

    def on_floor(self, x, y):
        """Over this room's own floor mesh. Cast at the floor alone: a rug half under a sofa must not read the sofa as 'off the
        floor', and furniture-on-furniture is the footprint check's job. One BVH per room: Object.ray_cast rebuilds it per call,
        which cost minutes per item on a 50 m2 floor (2026-10-15)."""
        if getattr(self, "_bvh", None) is None:
            from mathutils.bvhtree import BVHTree
            self._inv = self.floor.matrix_world.inverted()
            self._bvh = BVHTree.FromObject(self.floor, bpy.context.evaluated_depsgraph_get())
        o, d = self._inv @ Vector((x, y, self.z + 1.0)), (self._inv.to_3x3() @ Vector((0, 0, -1))).normalized()
        return self._bvh.ray_cast(o, d, 1.5)[0] is not None

    def objects(self, everything):
        x0, x1, y0, y1 = self.box
        return [o for o in everything if (f := footprint(o)) and f[0] < x1 and x0 < f[1] and f[2] < y1 and y0 < f[3]
                and f[4] < self.z + 2.0]


def _local_points(o):
    """Bound-box corners of o and its children in o's unrotated, unscaled frame (o's own origin)."""
    inv = o.matrix_world.inverted()
    return [inv @ (x.matrix_world @ Vector(c)) for x in [o, *o.children_recursive] if x.type == "MESH" for c in x.bound_box] \
        or [Vector()]


def _place(o, x, y, yaw, room, obstacles, front_axis):
    """Stand o on the floor at (x, y), its front (local front_axis) turned to yaw; refuse a spot off the floor or touching anything.

    The candidate footprint is computed from o's local box, not by moving o: a view-layer update per candidate cost minutes per
    item on a full apartment (2026-10-15). Only an accepted spot touches the scene. Like before, o stands upright (x/y rotation 0)."""
    rz = yaw - math.atan2(front_axis[1], front_axis[0])
    R = Matrix.Rotation(rz, 3, "Z") @ Matrix.Diagonal(o.scale)
    pts = [R @ p for p in _local_points(o)]
    f0 = (min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts),
          min(p.z for p in pts), max(p.z for p in pts))                       # relative to o's origin
    dx, dy = x - (f0[0] + f0[1]) / 2, y - (f0[2] + f0[3]) / 2                # origin position that centres the box on (x, y)
    f = (f0[0] + dx, f0[1] + dx, f0[2] + dy, f0[3] + dy, room.z, room.z + (f0[5] - f0[4]))
    corners = [(f[0] + 0.05, f[2] + 0.05), (f[1] - 0.05, f[2] + 0.05), (f[0] + 0.05, f[3] - 0.05), (f[1] - 0.05, f[3] - 0.05),
               ((f[0] + f[1]) / 2, (f[2] + f[3]) / 2)]
    if any(_overlap(f, b) for b in obstacles) or not all(room.on_floor(cx, cy) for cx, cy in corners):
        return False
    # glTF-imported assets (ABO/HSSD/Poly Haven via abo_assets) come in with rotation_mode QUATERNION, where rotation_euler is
    # ignored: every such chair, desk and sofa kept its import orientation (r5, 2026-10-16: all chairs faced one world direction)
    o.rotation_mode = "XYZ"
    o.rotation_euler = (0, 0, rz)
    o.location = (dx, dy, room.z - f0[4] + 0.002)
    bpy.context.view_layer.update()
    obstacles.append(f)
    return True


def _free_walls(room, rng, n=60):
    """(point at floor+0.4 m on this room's wall, inward normal, free run along the wall in m), longest first."""
    spots = rd._wall_spots(room.scene, room.deps, {"floor": room.floor, "wall": room.wall}, rng, room.z + 0.4)
    out = []
    for p, nrm in spots[:n]:
        side = nrm.cross(Vector((0, 0, 1))).normalized()
        run = 0.0
        for k in range(1, 15):                                  # how far the wall stays flat and unobstructed either way
            ok = True
            for sgn in (1, -1):
                q = p + side * (sgn * 0.15 * k)
                hit = room.scene.ray_cast(room.deps, q + nrm * 0.4, -nrm, distance=0.5)
                if not hit[0] or hit[4] != room.wall or abs((hit[1] - q).length) > 0.05:
                    ok = False
            if not ok:
                break
            run = 0.3 * k
        out.append((p, nrm, run))
    out.sort(key=lambda t: -t[2])
    return out


# ---- room programmes ----------------------------------------------------------------------------------------------------------------
ABO_FRONT = (0.0, -1.0)
INF_FRONT = (1.0, 0.0)


CEILING_KIT = {"plaster_white": (0.78, 0.77, 0.74), "exposed_white": (0.8, 0.8, 0.79), "exposed_dark": (0.035, 0.035, 0.037),
               "dark_painted": (0.03, 0.028, 0.026), "timber_slats": (0.45, 0.32, 0.2)}
#: set by the activity pass from the plan's style kit (non-home 20: a white ceiling over a dark moody café broke the style)
CEILING = {"kind": "plaster_white"}


def white_ceilings(stats):
    kind = CEILING.get("kind", "plaster_white")
    m = bpy.data.materials.get(f"ir_ceiling_{kind}")
    if m is None:
        m = bpy.data.materials.new(f"ir_ceiling_{kind}"); m.use_nodes = True
        b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = (*CEILING_KIT.get(kind, CEILING_KIT["plaster_white"]), 1); b.inputs["Roughness"].default_value = 0.92
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name.endswith(".ceiling"):
            for s in o.material_slots:
                s.material = m
            stats["ceilings_whitened"] += 1


def dining_chairs(room, everything, obstacles, rng, stats):
    tables = [o for o in room.objects(everything) if rd._factory(o.name) == "TableDiningFactory"]
    chairs = [o for o in room.objects(everything) if rd._factory(o.name) in ("ChairFactory", "BarChairFactory")]
    if not tables or not chairs:
        return
    t = tables[0]; tf = footprint(t)
    cx, cy = (tf[0] + tf[1]) / 2, (tf[2] + tf[3]) / 2
    long_x = (tf[1] - tf[0]) >= (tf[3] - tf[2])
    length = max(tf[1] - tf[0], tf[3] - tf[2])
    per_side = max(1, min(3, int(length / 0.6)))
    proto = chairs[0]
    for side in (-1, 1):
        for k in range(per_side):
            off = (k - (per_side - 1) / 2) * 0.6
            if long_x:
                x, y = cx + off, (tf[2] if side < 0 else tf[3]) + side * 0.32
                face = math.atan2(cy - y, 0)
            else:
                x, y = (tf[0] if side < 0 else tf[1]) + side * 0.32, cy + off
                face = math.atan2(0, cx - x)
            if any(abs((footprint(c)[0] + footprint(c)[1]) / 2 - x) < 0.3 and abs((footprint(c)[2] + footprint(c)[3]) / 2 - y) < 0.3
                   for c in chairs):
                continue                                         # a chair already sits here
            c = proto.copy(); c.data = proto.data; bpy.context.scene.collection.objects.link(c)
            c.name = f"{rd._factory(proto.name)}(dup).spawn_asset({stats['dining_chairs_added']})"
            if _place(c, x, y, face, room, obstacles, INF_FRONT):
                stats["dining_chairs_added"] += 1
            else:
                bpy.data.objects.remove(c, do_unlink=True)


def living_set(room, everything, obstacles, rng, stats, spawn_decor, rugzones):
    have = {rd._factory(o.name) for o in room.objects(everything)}
    walls = _free_walls(room, rng)
    for p, nrm, run in walls:
        if run < 2.2:
            break
        if "SofaFactory" in have:
            break
        sofa = AboPick("sofa", rng).spawn(stats["furniture_added"])
        sofa_depth = sofa.dimensions[1]
        pos = p + nrm * (sofa_depth / 2 + 0.03)
        if not _place(sofa, pos.x, pos.y, math.atan2(nrm.y, nrm.x), room, obstacles, ABO_FRONT):
            bpy.data.objects.remove(sofa, do_unlink=True)
            continue
        stats["furniture_added"] += 1
        side = nrm.cross(Vector((0, 0, 1))).normalized()
        face = math.atan2(nrm.y, nrm.x)
        coffee = AboPick("coffee", rng).spawn(stats["furniture_added"])
        coffee_w, coffee_d = coffee.dimensions[0], coffee.dimensions[1]
        ct = pos + nrm * (sofa_depth / 2 + 0.45 + coffee_d / 2)
        coffee_ok = _place(coffee, ct.x, ct.y, face, room, obstacles, ABO_FRONT)
        if coffee_ok:
            stats["furniture_added"] += 1
            spawn_decor(coffee)
        else:
            bpy.data.objects.remove(coffee, do_unlink=True)
        rug = AboPick("rug", rng).spawn(stats["furniture_added"])
        rc = pos + nrm * (sofa_depth / 2 + 0.6)
        if _place(rug, rc.x, rc.y, face, room, rugzones, ABO_FRONT):     # rugs go under furniture: only doors and rugs block them
            stats["furniture_added"] += 1
        else:
            bpy.data.objects.remove(rug, do_unlink=True)
        for sgn, key in ((1, "side"), (-1, "floorlamp")):
            o = AboPick(key, rng).spawn(stats["furniture_added"])
            q = pos + side * sgn * (sofa.dimensions[0] / 2 + 0.05 + o.dimensions[0] / 2)
            if _place(o, q.x, q.y, face, room, obstacles, ABO_FRONT):
                stats["furniture_added"] += 1
            else:
                bpy.data.objects.remove(o, do_unlink=True)
        arm = AboPick("armchair", rng).spawn(stats["furniture_added"])
        q = ct + side * ((coffee_w / 2 + 0.5 + arm.dimensions[0] / 2) if coffee_ok else 1.2)
        if _place(arm, q.x, q.y, math.atan2(-side.y, -side.x), room, obstacles, ABO_FRONT):
            stats["furniture_added"] += 1
        else:
            bpy.data.objects.remove(arm, do_unlink=True)
        break


def _under(box, p):
    return box[0] <= p.x <= box[1] and box[2] <= p.y <= box[3]


def bedroom_set(room, everything, obstacles, rng, stats, rugzones):
    beds = [o for o in room.objects(everything) if rd._factory(o.name) == "BedFactory"]
    for bed in beds[:1]:
        fwd = (bed.matrix_world.to_3x3() @ Vector((1, 0, 0))).normalized()        # Infinigen front +x: the foot
        side = fwd.cross(Vector((0, 0, 1))).normalized()
        bf = footprint(bed); c = Vector(((bf[0] + bf[1]) / 2, (bf[2] + bf[3]) / 2, room.z))
        half_len = abs((Vector((bf[1] - bf[0], bf[3] - bf[2], 0)) * 0.5).dot(fwd)) or bed.dimensions[0] / 2
        half_w = abs((Vector((bf[1] - bf[0], bf[3] - bf[2], 0)) * 0.5).dot(side)) or bed.dimensions[1] / 2
        face = math.atan2(fwd.y, fwd.x)
        for sgn in (1, -1):
            ns = AboPick("nightstand", rng).spawn(stats["furniture_added"])
            q = c - fwd * (half_len - ns.dimensions[1] / 2 - 0.05) + side * sgn * (half_w + 0.05 + ns.dimensions[0] / 2)
            if _place(ns, q.x, q.y, face, room, obstacles, ABO_FRONT):
                stats["furniture_added"] += 1
            else:
                bpy.data.objects.remove(ns, do_unlink=True)
        rug = AboPick("rug", rng).spawn(stats["furniture_added"])
        q = c + fwd * (half_len * 0.6)
        if _place(rug, q.x, q.y, face + math.pi / 2, room, rugzones, ABO_FRONT):
            stats["furniture_added"] += 1
        else:
            bpy.data.objects.remove(rug, do_unlink=True)
    for p, nrm, run in _free_walls(room, rng):
        if run < 1.2:
            break
        dr = AboPick("dresser", rng).spawn(stats["furniture_added"])
        pos = p + nrm * (dr.dimensions[1] / 2 + 0.03)
        if _place(dr, pos.x, pos.y, math.atan2(nrm.y, nrm.x), room, obstacles, ABO_FRONT):
            stats["furniture_added"] += 1
            break
        bpy.data.objects.remove(dr, do_unlink=True)


HANGING = ("WallArtFactory", "MirrorFactory", "CeilingLightFactory", "CeilingClassicLampFactory", "AboCeilingFixtureFactory",
           "CeilingBeamFactory", "SoffitFactory", "DuctFactory", "PipeFactory", "TrackRailFactory", "TrackSpotFactory", "AcCassetteFactory",
           "SprinklerFactory", "CeilingGridFactory", "LinearLedFactory", "DiffuserFactory", "SmokeDetectorFactory", "LinearPendantFactory",
           "RoofDeckFactory", "RoofGirderFactory", "HighBayCordFactory", "HighBayLampFactory")   # warehouse roof (whC r2: the deck blocked the floor)


def obstacles(everything):
    """(footprints furniture must clear, door zones + flat things rugs must clear); the door zones are in both.

    Rugs and mats (< 5 cm tall) block only other rugs -- furniture stands on them (an existing 2x3 m rug made a living room
    reject every armchair, 2026-10-15) -- and wall/ceiling-hung things block nothing on the floor."""
    obst, flat = [], []
    for o in everything:
        if rd._factory(o.name) in HANGING or "Window" in rd._factory(o.name) or o.type == "LIGHT" or o.hide_render or not o.visible_get():
            continue                                            # hidden asset templates sit at the origin; they block nothing
        f = footprint(o)
        if f[4] > 1.9:                                          # anything hung above head height blocks nothing on the floor: the flagship hall's
            continue                                            # ducts / trays / beams were not in HANGING, so 35 of 35 pieces were refused
        (flat if f[5] - f[4] < 0.05 else obst).append(f)
    doors = []                                                  # door swing / passage kept clear of everything
    # measured from the casing (the opening), not the leaf: an open leaf -- or a leaf mesh whose box spans its baked swing -- made the
    # zone 1.8 m deep and pushed meeting tables against the far wall (office r6, 2026-10-16). Leaves only where a door has no casing.
    door_objs = [o for o in everything if "Door" in rd._factory(o.name)]
    casings = [o for o in door_objs if "Casing" in rd._factory(o.name)]
    for o in casings or door_objs:
        f = footprint(o)
        doors.append((f[0] - DOOR_CLEAR_M, f[1] + DOOR_CLEAR_M, f[2] - DOOR_CLEAR_M, f[3] + DOOR_CLEAR_M, f[4], f[5]))
    return obst + doors, flat + doors


def furnish(rng, stats, spawn_decor, skip=()):
    """spawn_decor(table_obj): puts a few things on a new coffee table (the activity pass's surface placer). Rooms in skip are
    left to the room planner's realizer."""
    for k in ("ceilings_whitened", "dining_chairs_added", "furniture_added"):
        stats.setdefault(k, 0)
    white_ceilings(stats)
    scene, deps = bpy.context.scene, bpy.context.evaluated_depsgraph_get()
    everything = rd._tops()
    obstacles_, rugzones = obstacles(everything)
    for name, parts in sorted(rd._rooms().items()):
        if "floor" not in parts or "wall" not in parts or name in skip:
            continue
        room = Room(name, parts, scene, deps)
        if room.type == "dining-room":
            dining_chairs(room, everything, obstacles_, rng, stats)
        elif room.type == "living-room":
            living_set(room, everything, obstacles_, rng, stats, spawn_decor, rugzones)
        elif room.type == "bedroom":
            bedroom_set(room, everything, obstacles_, rng, stats, rugzones)
        deps = bpy.context.evaluated_depsgraph_get(); room.deps = deps
