"""Activity-centric small-object pass on a generated Infinigen apartment (user 2026-10-13).

The solver keeps the furniture (and the anchors standing on it: monitor, TV, lamps, microwave); every other small object it placed is
removed and the surfaces are refurnished by what a household does at each piece of furniture:

  desk -> working (lamp, cup, books, plant)        dining table -> a meal for the chairs present, or a centrepiece
  coffee/side table -> living (books, cup, bowl)   bedside table -> lamp, book, cup
  kitchen counter -> clustered jars/bottles/cans at the wall, a pot or pan, fruit, food boxes
  bookcase shelf -> rows of standing books, a few decor pieces, some shelves left empty
  bathroom sink -> bottles at the back, a cup

Placement is rule-based, no annealing: support surfaces come from ray casting the furniture (open shelves: every level; closed
furniture: the top only), an item goes where its whole footprint is supported, under the clearance, clear of the others.

House-level knobs, recorded in the sidecar: tidiness (0 messy .. 1 tidy; per room +-0.1) sets counts, empty shelves, yaw jitter and
meal probability; one fabric palette per house (a subset of tidy_objects_infinigen2.FABRIC) colours every upholstered piece. Wall art
and screens go through tidy_objects_infinigen2.hang_art.

Runs in the infinigen env (bpy as a module):
    python activity_pass_infinigen2.py IN.blend --out OUT.blend --solve-state solve_state.json [--seed N] [--tidiness T]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
import time
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tidy_objects_infinigen2 as tidy                                       # noqa: E402
from infinigen.assets.objects import appliances, lamp, small_plants, table_decorations as td, tableware as tw, wall_decorations   # noqa: E402
import room_dressing  # noqa: E402
import furnish_rooms  # noqa: E402

ROOM_RE = re.compile(r"^(?P<type>[a-z-]+)_\d+/\d+$")
KEEP = ("MonitorFactory", "TVFactory", "DeskLampFactory", "LampFactory", "MicrowaveFactory", "FloorLampFactory")
KIND = {"SimpleDeskFactory": "desk", "SidetableDeskFactory": "desk", "TableDiningFactory": "dining", "CoffeeTableFactory": "coffee",
        "TableCocktailFactory": "coffee", "SideTableFactory": "side", "TVStandFactory": "tvstand", "KitchenSpaceFactory": "kitchen",
        "KitchenCabinetFactory": "kitchen", "KitchenIslandFactory": "kitchen", "SimpleBookcaseFactory": "shelf",
        "CellShelfFactory": "shelf", "LargeShelfFactory": "shelf", "TriangleShelfFactory": "shelf", "WallShelfFactory": "shelf",
        "SingleCabinetFactory": "shelf", "BathroomSinkFactory": "bathsink", "StandingSinkFactory": "bathsink"}
OPEN_LEVELS = {"shelf", "tvstand"}               # every level is visible; elsewhere only the top surface is used
GRID = 0.03
MAX_Z = 1.85                                     # nothing goes on surfaces higher than this (world z): unreachable, rarely seen
DECOR = [(td.VaseFactory, 3), (tw.PlantContainerFactory, 3), (small_plants.SucculentFactory, 1), (td.BookStackFactory, 3)]
USE_ABO = False                  # --abo: ABO product models join the decor / lamp / plant pools (2026-10-14, new scenes only)


def decor():
    if not USE_ABO:
        return DECOR
    import abo_assets as abo
    return DECOR + [(abo.VASE, 3), (abo.PLANTER, 3), (abo.BOX, 1), (abo.CANDLE, 1)]


def desk_lamp(rng):
    if USE_ABO and rng.random() < 0.5:
        import abo_assets as abo
        return abo.TABLE_LAMP
    return lamp.DeskLampFactory


def plant(rng):
    if USE_ABO and rng.random() < 0.5:
        import abo_assets as abo
        return abo.PLANTER
    return weighted(rng, [(tw.PlantContainerFactory, 2), (small_plants.SucculentFactory, 1)])


def weighted(rng, items):
    return rng.choices([i for i, _ in items], [w for _, w in items])[0]


# ---- support surfaces ----------------------------------------------------------------------------------------------------------------
def supports(F, deps, top_only: bool) -> list:
    """Horizontal surfaces of furniture F in F's local frame: [{z, cells:{(ix,iy): clearance}, clear, x0,x1,y0,y1}] on a GRID lattice."""
    parts = [o for o in [F, *F.children_recursive] if o.type == "MESH"]
    inv = F.matrix_world.inverted()
    lo = np.array([min(c[i] for c in F.bound_box) for i in range(3)]); hi = np.array([max(c[i] for c in F.bound_box) for i in range(3)])
    for o in parts[1:]:                          # children may stick out of the parent's box
        m = inv @ o.matrix_world
        pts = np.array([(m @ Vector(c))[:] for c in o.bound_box])
        lo, hi = np.minimum(lo, pts.min(0)), np.maximum(hi, pts.max(0))
    down = Vector((0, 0, -1))
    boxes = []                                   # each part's box in F's frame: a ray only tests parts whose xy box it passes through
    for o in parts:
        m = inv @ o.matrix_world
        pts = np.array([(m @ Vector(c))[:] for c in o.bound_box])
        boxes.append((o, pts.min(0) - 1e-3, pts.max(0) + 1e-3))

    def first_hit(origin_l, dist):
        best = None
        for o in [o for o, bl, bh in boxes if bl[0] <= origin_l.x <= bh[0] and bl[1] <= origin_l.y <= bh[1] and bl[2] < origin_l.z]:
            m = o.matrix_world.inverted() @ F.matrix_world
            ok, loc, nrm, _ = o.ray_cast(m @ origin_l, (m.to_3x3() @ down).normalized(), distance=dist, depsgraph=deps)
            if ok:
                loc_l = m.inverted() @ loc
                n_l = (m.inverted().to_3x3().transposed().inverted() @ nrm).normalized()   # normal back into F's frame
                d = origin_l.z - loc_l.z
                if best is None or d < best[0]:
                    best = (d, loc_l, n_l)
        return best

    levels = {}
    for ix in range(int(math.floor(lo[0] / GRID)) + 1, int(math.ceil(hi[0] / GRID))):
        for iy in range(int(math.floor(lo[1] / GRID)) + 1, int(math.ceil(hi[1] / GRID))):
            # Hit order, not normal sign, says which face is a top: Infinigen meshes come with flipped normals (a dining table's top
            # read as a ceiling). A hit after a >6 cm gap is the top of a board; one within 6 cm of the previous is that board's underside.
            z, prev = hi[2] + 0.05, None
            while True:
                h = first_hit(Vector((ix * GRID, iy * GRID, z)), z - lo[2] + 0.01)
                if h is None:
                    break
                _, p, n = h
                if (prev is None or prev - p.z > 0.06) and abs(n.z) > 0.9:
                    key = round(p.z / 0.01)
                    lv = levels.setdefault(key, {"zs": [], "cells": {}, "clears": []})
                    c = (prev - p.z) if prev is not None else 1.5        # open top: room for a TV or a lamp
                    lv["zs"].append(p.z); lv["cells"][(ix, iy)] = c; lv["clears"].append(c)
                    if top_only:
                        break
                prev = p.z
                z = p.z - 0.004
    merged = {}                                  # a board that is not perfectly flat splits over neighbouring 1 cm keys (N2 r9: a rack's lowest deck came out as two half-empty checkerboards of cells, so no
    for key in sorted(levels):                   # carton's whole footprint was ever 'supported'): keys 1 cm apart are one level
        lv = levels[key]
        if merged and key - max(merged) <= 1:
            tgt = merged[max(merged)]
            for ck, cv in lv["cells"].items():
                tgt["cells"][ck] = max(cv, tgt["cells"].get(ck, 0.0))
            tgt["zs"] += lv["zs"]; tgt["clears"] += lv["clears"]
            merged[key] = tgt
        else:
            merged[key] = lv
    levels = {id(v): v for v in merged.values()}
    out = []
    for lv in levels.values():
        if len(lv["cells"]) * GRID * GRID < 0.03:
            continue
        xs = [c[0] for c in lv["cells"]]; ys = [c[1] for c in lv["cells"]]
        out.append({"z": float(np.median(lv["zs"])), "cells": lv["cells"], "clear": float(np.percentile(lv["clears"], 20)),
                    "x0": min(xs) * GRID, "x1": max(xs) * GRID, "y0": min(ys) * GRID, "y1": max(ys) * GRID, "placed": []})
    return sorted(out, key=lambda s: -s["z"])


# ---- placing one item -------------------------------------------------------------------------------------------------------------
def footprint(o, rel_yaw, lie=False):
    """o's local box after (optional) lying down and turning by rel_yaw: (corners_xy (4,2) centred, height, centre offset, zmin)."""
    R = Matrix.Rotation(rel_yaw, 4, "Z") @ (Matrix.Rotation(math.pi / 2, 4, "X") if lie else Matrix.Identity(4))
    pts = np.array([(R @ Vector(c))[:] for c in o.bound_box])
    lo, hi = pts.min(0), pts.max(0)
    return R, lo, hi


MARGIN = float(os.environ.get("ROOM_PLACE_MARGIN") or 0.01)     # half the clearance kept between two placed footprints; S38 r10: shelf facings at 0.003 sit ~1 cm apart, not 3 cm


def try_place(o, F, s, rng, hint, yaw_sigma, lie=False, rel_yaw=None, at=None, tries=30, jitter=0.03) -> bool:
    """Put o on support s of F: the whole footprint on supported cells, under the clearance, clear of what is already there."""
    if rel_yaw is None:
        rel_yaw = rng.choice((0, math.pi / 2, math.pi, -math.pi / 2)) + rng.gauss(0, yaw_sigma)
    R, lo, hi = footprint(o, rel_yaw, lie)
    w, d, h = hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]
    if h > s["clear"] - 0.01 or w > s["x1"] - s["x0"] or d > s["y1"] - s["y0"]:
        return False
    for _ in range(tries):
        if at is not None:
            cx, cy = at[0] + rng.gauss(0, jitter), at[1] + rng.gauss(0, jitter)
        elif hint == "back":                     # back = -x (tagging.py: Front is max x)
            cx, cy = s["x0"] + w / 2 + rng.uniform(0.01, 0.06), rng.uniform(s["y0"] + d / 2, s["y1"] - d / 2)
        elif hint == "center":
            cx = (s["x0"] + s["x1"]) / 2 + rng.gauss(0, 0.03); cy = (s["y0"] + s["y1"]) / 2 + rng.gauss(0, (s["y1"] - s["y0"]) * 0.12)
        else:
            cx, cy = rng.uniform(s["x0"] + w / 2, s["x1"] - w / 2), rng.uniform(s["y0"] + d / 2, s["y1"] - d / 2)
        box = (cx - w / 2 - MARGIN, cx + w / 2 + MARGIN, cy - d / 2 - MARGIN, cy + d / 2 + MARGIN)
        if any(box[0] < b[1] and b[0] < box[1] and box[2] < b[3] and b[2] < box[3] for b in s["placed"]):
            continue
        gx = np.arange(cx - w / 2 + 0.01, cx + w / 2 - 0.009, GRID / 2); gy = np.arange(cy - d / 2 + 0.01, cy + d / 2 - 0.009, GRID / 2)
        if not all(s["cells"].get((int(round(x / GRID)), int(round(y / GRID))), 0) > h + 0.01 for x in gx for y in gy):   # dividers: no room
            continue
        off = Vector((-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]))
        o.matrix_world = F.matrix_world @ Matrix.Translation(Vector((cx, cy, s["z"])) + off) @ R
        s["placed"].append(box)
        return True
    return False


class Spawner:
    def __init__(self, seed, stats):
        # % 2**24: factories add their own offsets to the seed; LargePlantContainerFactory overflowed numpy's 2**32 from 2**31 bases
        self.seed, self.i, self.stats = seed % 2 ** 24, 0, stats

    def __call__(self, cls, **attrs):
        self.i += 1
        try:
            fac = cls(self.seed + self.i)
            for k, v in attrs.items():
                setattr(fac, k, v)
            o = fac.spawn_asset(self.i)
            bpy.context.view_layer.update()
            return o
        except Exception as exc:              # one factory failing must not cost the scene
            self.stats["spawn_failed"][cls.__name__] = self.stats["spawn_failed"].get(cls.__name__, 0) + 1
            print("[activity] spawn failed", cls.__name__, exc, flush=True)
            return None


def put(spawn, cls, F, s, rng, hint, t, stats, lie=False, rel_yaw=None, at=None, **attrs) -> bool:
    o = spawn(cls, **attrs)
    if o is None:
        return False
    if try_place(o, F, s, rng, hint, yaw_sigma=math.radians(12) * (1 - t), lie=lie, rel_yaw=rel_yaw, at=at):
        stats["placed"][cls.__name__] = stats["placed"].get(cls.__name__, 0) + 1
        return True
    tidy.delete(o)
    stats["no_room"] += 1
    return False


# ---- activities ---------------------------------------------------------------------------------------------------------------------
#: Book cloth and packaging, sRGB hex. Infinigen prints both with its procedural "graphic design" text material, which reads as
#: neon gibberish (user 2026-10-14); a per-book colour from these palettes replaces it.
BOOK_CLOTH = ["7a2e2a", "8c3b2f", "2f3e5c", "3b4a6b", "2e4a3a", "4f5d3a", "1f1f22", "3a3633", "5a4232", "8a6a4a",
              "c9bfa8", "d8d0bc", "9a8f7d", "6b2f4a", "4a5a66", "b0874a"]
PACKAGING = ["c43b2e", "e0a030", "2f6db0", "3c8c4a", "e8e2d4", "f2f0ea", "7a3fa0", "d0602a", "2a2a2a", "b8c9d8"]
PRINTED = ("BookColumnFactory", "BookStackFactory", "BookFactory", "FoodBoxFactory", "FoodBagFactory", "CanFactory")


def plain_material(name, palette):
    """One colour per mesh island (= one book of a joined column/stack), shifted per object, from a constant colour ramp."""
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; b = nt.nodes["Principled BSDF"]
    geo = nt.nodes.new("ShaderNodeNewGeometry"); info = nt.nodes.new("ShaderNodeObjectInfo")
    add = nt.nodes.new("ShaderNodeMath"); add.operation = "ADD"
    frac = nt.nodes.new("ShaderNodeMath"); frac.operation = "FRACT"
    nt.links.new(geo.outputs["Random Per Island"], add.inputs[0]); nt.links.new(info.outputs["Random"], add.inputs[1])
    nt.links.new(add.outputs[0], frac.inputs[0])
    ramp = nt.nodes.new("ShaderNodeValToRGB"); ramp.color_ramp.interpolation = "CONSTANT"
    els = ramp.color_ramp.elements
    while len(els) < len(palette):
        els.new(0.5)
    for i, (e, hx) in enumerate(zip(els, palette)):
        e.position = i / len(palette); e.color = (*tidy.lin(hx), 1.0)
    nt.links.new(frac.outputs[0], ramp.inputs["Fac"]); nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.6
    return m


def _has_product_label(m):
    """True when the material's image node already carries one of the generated product-label designs."""
    if not m.use_nodes:
        return False
    return any(n.type == "TEX_IMAGE" and n.image is not None and any(k in (n.image.filepath or "") for k in ("product_labels", "pharmacy_pack_labels", "pack_atlas")) for n in m.node_tree.nodes)


def plain_prints(stats):
    """Swap the procedural print on books and packaging for plain per-item colours."""
    books, pack = plain_material("ir_book_cloth", BOOK_CLOTH), plain_material("ir_packaging", PACKAGING)
    for o in tidy.tops():
        f = tidy.factory(o.name)
        if f not in PRINTED:
            continue
        for ob in [o, *o.children_recursive]:
            for slot in getattr(ob, "material_slots", []):
                if slot.material and tidy.ART_MAT.match(slot.material.name):
                    if _has_product_label(slot.material):    # printed packaging from room_planner (data/venue_refs/product_labels) stays:
                        continue                              # the plain per-item colours below made every shelf good a flat block
                    slot.material = books if f.startswith("Book") else pack
                    stats["prints_replaced"] += 1


def book_row(spawn, F, s, rng, t, stats):
    """Standing books along the shelf width (F's local y), from one end, filling 40-90%."""
    width = s["y1"] - s["y0"]
    goal, used = rng.uniform(0.4, 0.9) * width, 0.0
    n = rng.randint(8, 16)
    for _ in range(6):
        if used >= goal or n < 3:
            break
        o = spawn(td.BookColumnFactory, n_books=n, max_angle=rng.uniform(0.0, 0.05))   # Infinigen leans up to 20 deg: a zigzag row
        if o is None:
            return
        if not try_place(o, F, s, rng, "any", yaw_sigma=0, rel_yaw=math.pi / 2):
            tidy.delete(o); stats["no_room"] += 1
            n //= 2                                 # too wide or too tall for what is left: a shorter run of books
            continue
        stats["placed"]["BookColumnFactory"] = stats["placed"].get("BookColumnFactory", 0) + 1
        used += o.dimensions[0]


def furnish(kind, room, F, levels, spawn, rng, t, ctx, stats):
    top = [s for s in levels if (F.matrix_world @ Vector((0, 0, s["z"]))).z < MAX_Z]
    if not top:
        return
    s = top[0]
    p = lambda x: rng.random() < x
    # With solve_small off (infinigen_gen.py --small-objects activity) the solver no longer puts TVs, monitors or lamps on top of
    # furniture either; an existing one (solver-placed) is kept and recorded in ctx["has"].
    if kind == "tvstand" and "TV" not in ctx["has"].get(F.name, ()):
        put(spawn, appliances.TVFactory, F, s, rng, "center", t, stats, rel_yaw=0.0)
    if kind == "desk" and "Monitor" not in ctx["has"].get(F.name, ()) and p(0.6):
        put(spawn, appliances.MonitorFactory, F, s, rng, "back", t, stats, rel_yaw=0.0)
    if kind == "desk":
        if not ctx["lamp_on"].get(F.name) and p(0.5):
            put(spawn, desk_lamp(rng), F, s, rng, "back", t, stats)
        if p(0.2 + 0.5 * (1 - t)):
            put(spawn, tw.CupFactory, F, s, rng, "any", t, stats)
        if p(0.6):
            put(spawn, td.BookStackFactory, F, s, rng, "any", t, stats)
        if p(0.4):
            put(spawn, plant(rng), F, s, rng, "back", t, stats)
    elif kind == "dining":
        chairs = max(2, min(6, ctx["chairs"].get(room, 0)))
        if p(0.15 + 0.35 * (1 - t)):                          # a meal laid for some of the chairs
            long_y = (s["y1"] - s["y0"]) >= (s["x1"] - s["x0"])
            for k in range(rng.randint(1, chairs)):
                side = k % 2
                frac = (k // 2 + 0.5) / max(1, math.ceil(chairs / 2))
                if long_y:
                    at = (s["x0"] + 0.18 if side == 0 else s["x1"] - 0.18, s["y0"] + frac * (s["y1"] - s["y0"]))
                else:
                    at = (s["x0"] + frac * (s["x1"] - s["x0"]), s["y0"] + 0.18 if side == 0 else s["y1"] - 0.18)
                if put(spawn, tw.PlateFactory, F, s, rng, None, t, stats, at=at):
                    put(spawn, rng.choice((tw.CupFactory, tw.WineglassFactory)), F, s, rng, None, t, stats,
                        at=(at[0] + (0.0 if long_y else 0.16), at[1] + (0.16 if long_y else 0.0)))
            stats["meals"] += 1
        elif p(0.75):
            put(spawn, weighted(rng, [(tw.FruitContainerFactory, 2), (td.VaseFactory, 2), (tw.BowlFactory, 1)] + ([(__import__("abo_assets").VASE, 2), (__import__("abo_assets").PLANTER, 1)] if USE_ABO else [])), F, s, rng, "center", t, stats)
    elif kind in ("coffee", "side"):
        bedside = room == "bedroom"
        if bedside and not ctx["lamp_on"].get(F.name) and p(0.6):
            put(spawn, desk_lamp(rng), F, s, rng, "back", t, stats)
        n = 1 + int(rng.random() * 2.5 * (1 - t) + 0.3)
        pool = ([(td.BookStackFactory, 3), (tw.CupFactory, 2)] if bedside else
                [(td.BookStackFactory, 3), (tw.CupFactory, 2), (tw.FruitContainerFactory, 1), (td.VaseFactory, 2), (tw.BowlFactory, 1)])
        for _ in range(n):
            put(spawn, weighted(rng, pool), F, s, rng, "any", t, stats)
    elif kind == "kitchen":
        for s in [x for x in top if x["clear"] > 0.12][:1]:
            y_at = rng.uniform(s["y0"], s["y1"])
            for _ in range(rng.randint(2, 5)):              # the jar-and-bottle corner against the wall
                put(spawn, weighted(rng, [(tw.JarFactory, 3), (tw.BottleFactory, 3), (tw.CanFactory, 2)]), F, s, rng, None, t, stats,
                    at=(s["x0"] + 0.08, y_at + rng.uniform(-0.25, 0.25)))
            if p(0.3 + 0.4 * (1 - t)):
                put(spawn, rng.choice((tw.PotFactory, tw.PanFactory)), F, s, rng, "any", t, stats)
            if p(0.5):
                put(spawn, tw.FruitContainerFactory, F, s, rng, "any", t, stats)
            for _ in range(rng.randint(0, 2)):
                put(spawn, tw.FoodBoxFactory, F, s, rng, "back", t, stats)
            if p(0.4 * (1 - t)):
                put(spawn, tw.FoodBagFactory, F, s, rng, "any", t, stats, lie=True)
    elif kind == "bathsink":
        for _ in range(rng.randint(1, 3)):
            put(spawn, tw.BottleFactory, F, s, rng, "back", t, stats)
        if p(0.4):
            put(spawn, tw.CupFactory, F, s, rng, "back", t, stats)
    elif kind in ("shelf", "tvstand"):
        for s in top:
            if s["clear"] < 0.12:
                continue
            r = rng.random()
            if r < 0.1 + 0.25 * t:
                stats["shelves_left_empty"] += 1
                continue
            if kind == "shelf" and r < 0.75 and 0.2 < s["clear"] < 0.59:      # a board above: books stand in shelves, not on top
                book_row(spawn, F, s, rng, t, stats)
                if p(0.4):
                    put(spawn, weighted(rng, decor()), F, s, rng, "any", t, stats)
            else:
                for _ in range(rng.randint(1, 2)):
                    put(spawn, weighted(rng, decor()), F, s, rng, "any", t, stats)


def mark_occupied(F, levels, corners) -> set:
    """Whatever already stands on a level of F is an obstacle there -- a kept lamp, monitor or TV whatever relation the solver
    recorded for it (a desk lamp was missed when only F's own relation children counted: books went through its base).
    corners: name -> world bound-box points. Returns the factories found standing on F."""
    inv, found = F.matrix_world.inverted(), set()
    for other_name, wpts in corners.items():
        if other_name == F.name:
            continue
        pts = np.array([(inv @ Vector(c))[:] for c in wpts])
        lo, hi = pts.min(0), pts.max(0)
        for s in levels:
            if abs(lo[2] - s["z"]) < 0.05 and lo[0] < s["x1"] and s["x0"] < hi[0] and lo[1] < s["y1"] and s["y0"] < hi[1]:
                s["placed"].append((lo[0], hi[0], lo[1], hi[1]))
                found.add(tidy.factory(other_name))
    return found


def corners_of(objs) -> dict:
    return {o.name: [(x.matrix_world @ Vector(c))[:] for x in [o, *o.children_recursive] for c in x.bound_box] for o in objs}


# ---- scene -------------------------------------------------------------------------------------------------------------------------
def scene_index(solve_state: Path):
    """blender name -> room type for furniture on a room floor; small objects resting on furniture (to remove); chairs per room."""
    objs = json.loads(solve_state.read_text())["objs"]
    room_of, small, chairs = {}, set(), {}
    for rec in objs.values():
        name = rec.get("obj")
        for r in rec.get("relations", []):
            m = ROOM_RE.match(r["target_name"])
            if m and name:
                room_of.setdefault(name, m.group("type"))
            parent = objs.get(r["target_name"], {})
            if r["relation"].get("relation_type") == "StableAgainst" and "Subpart(support)" in r["relation"].get("parent_tags", []) \
                    and parent.get("obj") and name and not m:        # on furniture; a room floor (rooms carry an obj too) is not
                small.add(name)
    for name, room in room_of.items():
        if tidy.factory(name) in ("ChairFactory", "BarChairFactory"):
            chairs[room] = chairs.get(room, 0) + 1
    return room_of, small, chairs


NEVER_DROP = ("WallArtFactory", "MirrorFactory", "AboCeilingFixtureFactory", "SprinklerFactory", "BaseboardFactory")


def incremental(a, only: set) -> int:
    """ROOM_ONLY=<room ids>: start from the previous round's PRE-KIT post-activity blend (a.blend), remove the objects of just these rooms and re-realize them from --plans; every other step of
    the full pass (small-object clear, surface dressing, furnish_rooms of unplanned rooms, ceiling fixtures, art / fabric) is NOT repeated, so the rest of the floor stays bit-identical.
    Objects are removed by their ir_room tag (set by realize.realize); an older untagged blend falls back to 'not in scene_arch.blend and its footprint centre lies in the room's floor box'."""
    import os
    t0 = time.time()
    rng = random.Random(a.seed)
    stats = {"removed": 0, "kept_anchors": 0, "placed": {}, "no_room": 0, "meals": 0, "shelves_left_empty": 0, "spawn_failed": {}, "furniture": {}, "fabric_materials": 0, "paintings": 0, "screens": 0,
             "incremental_rooms": sorted(only)}
    gone = 0
    for o in list(bpy.data.objects):
        if o.get("ir_room") in only:
            bpy.data.objects.remove(o, do_unlink=True); gone += 1
    arch = Path(a.blend).parent / "scene_arch.blend"
    arch_names = set()
    if arch.exists():
        with bpy.data.libraries.load(str(arch), link=True) as (src, _dst):
            arch_names = set(src.objects)
    rooms = room_dressing._rooms()
    for rid in sorted(only):
        parts = rooms.get(rid)
        if not parts or "floor" not in parts:
            continue
        pts = [parts["floor"].matrix_world @ Vector(c) for c in parts["floor"].bound_box]
        x0, x1, y0, y1 = min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts)
        for o in list(tidy.tops()):
            if o.name in arch_names or o.get("ir_room") or tidy.factory(o.name) in NEVER_DROP or o.name.startswith(rid):
                continue
            c = o.matrix_world.translation
            if x0 <= c.x <= x1 and y0 <= c.y <= y1 and o.type == "MESH":
                tidy.delete(o); gone += 1
    stats["incremental_removed"] = gone
    bpy.context.view_layer.update()
    spawn = Spawner((a.seed * 1000) % 2 ** 31, stats)
    plans = json.loads(a.plans.read_text())
    _kit = plans.get("style_spec") or {}
    kit = _kit.get("architecture") or {}
    if kit.get("ceiling"):
        furnish_rooms.CEILING["kind"] = kit["ceiling"]
    from room_planner import realize
    import provenance
    provenance.configure(plans)
    stats["provenance_purged"] = provenance.purge(set(only))                              # the previous round's automatic dress objects in authoritative rooms
    with provenance.span("realize"):
        realize.realize(plans, rng, stats, spawn, sys.modules[__name__])                   # ROOM_ONLY inside realize filters the rooms
    provenance.write(a.out, stats)
    bpy.ops.wm.save_as_mainfile(filepath=a.out, compress=True)
    jp = Path(a.out + ".activity.json")                                                     # keep the full round's record; append this incremental run to it
    try:
        rec = json.loads(jp.read_text())
    except Exception:                                                                      # noqa: BLE001
        rec = {}
    rec.setdefault("incremental_runs", []).append({"rooms": sorted(only), "stats": {k: v for k, v in stats.items() if k != "furniture"}, "source": a.blend, "plans": str(a.plans), "secs": round(time.time() - t0)})
    rec["seed"] = rec.get("seed", a.seed)
    jp.write_text(json.dumps(rec, indent=1))
    print("ACTIVITY " + json.dumps({k: v for k, v in stats.items() if k != "furniture"}), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("blend")
    ap.add_argument("--out", required=True)
    ap.add_argument("--solve-state", required=True, type=Path)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tidiness", type=float, default=None, help="house tidiness 0..1 (default: sampled 0.35-0.9)")
    ap.add_argument("--abo", action="store_true", help="mix ABO product models into the decor, lamp and plant pools")
    ap.add_argument("--no-dressing", action="store_true", help="skip room_dressing (appliance finishes, lonely plants, wall decor)")
    ap.add_argument("--no-furnish", action="store_true", help="skip furnish_rooms (ceilings, dining chairs, living/bedroom sets)")
    ap.add_argument("--plans", type=Path, help="room_planner plan_scene.py output: planned rooms are furnished from it (realize.py)")
    a = ap.parse_args()
    global USE_ABO
    USE_ABO = a.abo
    t0 = time.time()
    bpy.ops.wm.open_mainfile(filepath=a.blend)
    _only = {x for x in __import__("os").environ.get("ROOM_ONLY", "").split(",") if x}
    if _only and a.plans:                                       # incremental round (per-room regeneration)
        return incremental(a, _only)
    rng = random.Random(a.seed)
    house_t = a.tidiness if a.tidiness is not None else rng.uniform(0.35, 0.9)
    palette = rng.sample(tidy.FABRIC, 6)
    stats = {"removed": 0, "kept_anchors": 0, "placed": {}, "no_room": 0, "meals": 0, "shelves_left_empty": 0, "spawn_failed": {},
             "furniture": {}, "fabric_materials": 0, "paintings": 0, "screens": 0}
    room_of, small, chairs = scene_index(a.solve_state)
    lamp_on, has = {}, {}
    tops = {o.name: o for o in tidy.tops()}
    rel = tidy.relations(a.solve_state)
    for name, o in list(tops.items()):
        if name not in small:
            continue
        if tidy.factory(name) in KEEP or max(o.dimensions) > 0.6:
            stats["kept_anchors"] += 1
            if rel.get(name, (None,))[0]:
                lamp_on[rel[name][0]] = lamp_on.get(rel[name][0], False) or "Lamp" in name
                has.setdefault(rel[name][0], set()).add("TV" if name.startswith("TVFactory") else "Monitor" if name.startswith("MonitorFactory") else "")
            continue
        tidy.delete(o); stats["removed"] += 1
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    alive = {o.name: o for o in tidy.tops()}
    room_t = {}
    corners = corners_of(alive.values())
    spawn = Spawner((a.seed * 1000) % 2 ** 31, stats)          # numpy seeds must stay below 2**32
    ctx = {"chairs": chairs, "lamp_on": lamp_on, "has": has}
    for name, F in sorted(alive.items()):
        kind = KIND.get(tidy.factory(name))
        if kind is None or name in small or name not in room_of:    # blend copies the solver never placed are not in the scene
            continue
        room = room_of.get(name, "unknown")
        t = room_t.setdefault(room, min(1.0, max(0.0, house_t + rng.gauss(0, 0.1))))
        levels = supports(F, deps, top_only=kind not in OPEN_LEVELS)
        for f in mark_occupied(F, levels, corners):
            if f in ("TVFactory", "MonitorFactory"):
                has.setdefault(name, set()).add(f.removesuffix("Factory"))
            if "Lamp" in f:
                lamp_on[name] = True
        before = sum(stats["placed"].values())
        furnish(kind, room, F, levels, spawn, rng, t, ctx, stats)
        stats["furniture"][name] = {"kind": kind, "room": room, "levels": len(levels), "placed": sum(stats["placed"].values()) - before}
        print(f"[activity] {name.split('.spawn')[0]} {kind}/{room}: {len(levels)} levels, placed {stats['furniture'][name]['placed']}", flush=True)
    fabric = {"fabric_materials": 0}
    stats.update(appliance_slots=0, lonely_plants_removed=0, wall_art_added=0, mirrors_added=0, rugs_muted=0)
    _kit = (json.loads(a.plans.read_text()).get("style_spec") or {}) if a.plans else {}
    import provenance                                          # per-object src tags + reference-authoritative gating of the automatic dress passes (tools/infinigen/provenance.py)
    provenance.configure(json.loads(a.plans.read_text()) if a.plans else {})
    if "framed_art" in (_kit.get("decor") or []):              # a styled venue hangs pictures (cafe refs: framed prints on the walls)
        for _rt in ("break-room", "cafe"):                     # clinics and shops borrow break-room too: one picture there, not a gallery
            room_dressing.ART_ROOMS[_rt] = 4 if _kit.get("venue") == "cafe" else _kit.get("art_count", 0) if _kit.get("venue") in (
                "clinic-reception", "exam-room", "dental-room", "physio-room") else _kit.get("art_count", 1)   # (clinic r9: 4 oil paintings; r15: even one reads as a home; kit key art_count: S20's ref hangs framed landscapes)
    if not a.no_dressing:
        room_dressing.neutral_appliances(rng, stats)
        room_dressing.mute_rugs(rng, stats)
        room_dressing.drop_lonely_floor_plants(stats)
        room_dressing.close_exterior_doors(stats)
        with provenance.gated("wall_art"):
            room_dressing.hang_wall_decor(rng, stats, spawn, wall_decorations.WallArtFactory, wall_decorations.MirrorFactory)
    if not a.no_furnish:
        def decor_on(F):                                        # a new coffee table gets what a used one carries
            levels = supports(F, bpy.context.evaluated_depsgraph_get(), top_only=True)
            if levels:
                for cls in rng.sample([td.BookStackFactory, tw.CupFactory, td.VaseFactory, tw.FruitContainerFactory, tw.BowlFactory], 2):
                    put(spawn, cls, F, levels[0], rng, "any", 0.5, stats)
        plans = json.loads(a.plans.read_text()) if a.plans else {"rooms": {}}
        kit = (plans.get("style_spec") or {}).get("architecture") or {}
        if kit.get("ceiling"):                                   # the style kit's ceiling (dark / exposed / timber), not always plaster
            furnish_rooms.CEILING["kind"] = kit["ceiling"]
        with provenance.span("furnish"):
            furnish_rooms.furnish(rng, stats, decor_on, skip=set(plans["rooms"]))
        if plans["rooms"]:
            from room_planner import realize
            with provenance.span("realize"):
                realize.realize(plans, rng, stats, spawn, sys.modules[__name__])
    if USE_ABO and not a.no_dressing:                           # after the furniture: pendants hang over the tables/counters it placed,
        import ceiling_fixtures                                 # and fixtures added to unlit rooms see the room as furnished
        with provenance.gated("ceiling_fixtures"):
            ceiling_fixtures.dress(rng, stats)
    stats["prints_replaced"] = 0
    plain_prints(stats)
    tidy.recolor_fabric(rng, fabric, palette=palette)
    if _kit.get("venue") in ("clinic-reception", "exam-room", "dental-room", "physio-room", "pharmacy"):   # wipe-clean vinyl seats
        from room_planner import proc_assets as _pa                # (clinic r19: velvet / beige fabric task chairs read as a home office)
        vinyl = _pa._flat("ir_clinic_vinyl", rng.choice(((0.04, 0.045, 0.05), (0.18, 0.2, 0.22), (0.05, 0.12, 0.2))), 0.35)
        for o in tidy.tops():
            if tidy.factory(o.name) == "OfficeChairFactory":
                for ob in [o, *o.children_recursive]:
                    for sl in getattr(ob, "material_slots", []):
                        if sl.material and tidy.FABRIC_MAT.match(sl.material.name):
                            sl.material = vinyl
    stats["fabric_materials"] = fabric["fabric_materials"]
    art = {"paintings": 0, "screens": 0}
    # a clinic monitor shows no painting (clinic r19: 'a full-colour painting on the exam monitor', a residential cue)
    with provenance.gated("art", "wall_art"):
        used = tidy.hang_art(rng, art, screens=_kit.get("venue") not in ("clinic-reception", "exam-room", "dental-room", "physio-room", "pharmacy"))
    if _kit.get("venue") in ("clinic-reception", "exam-room", "dental-room", "physio-room", "pharmacy"):
        # no art means the screen keeps Infinigen's text material, whose image is empty: magenta checker (clinic r24, 3 of 3) -- a dark
        # screen with a faint blue glow instead
        from room_planner import proc_assets as _pa2
        scr = _pa2._flat("ir_screen_dark", (0.02, 0.03, 0.05), 0.15)
        _b = scr.node_tree.nodes["Principled BSDF"]; _b.inputs["Emission Color"].default_value = (0.35, 0.5, 0.75, 1); _b.inputs["Emission Strength"].default_value = 0.4
        for o in tidy.tops():
            if tidy.factory(o.name) in ("MonitorFactory", "TVFactory"):
                for ob in [o, *o.children_recursive]:
                    for sl in getattr(ob, "material_slots", []):
                        m = sl.material
                        if m and (m.name.startswith("shader_text") or m.use_nodes and any(   # Infinigen's text screen: empty (magenta)
                                n.type == "TEX_IMAGE" and (n.image is None or not n.image.has_data) for n in m.node_tree.nodes)):   # or a
                            # colourful random graphic (clinic r27) -- both read wrong in a clinic
                            sl.material = scr
    stats.update(art)
    provenance.write(a.out, stats)                              # <blend>.provenance.json + stats['provenance'] / stats['non_reference_added'] per room
    bpy.ops.wm.save_as_mainfile(filepath=a.out, compress=True)
    Path(a.out + ".activity.json").write_text(json.dumps({"stats": stats, "house_tidiness": round(house_t, 3),
                                                          "room_tidiness": {k: round(v, 3) for k, v in room_t.items()},
                                                          "fabric_palette": palette, "art": used, "seed": a.seed, "abo": a.abo, "source": a.blend,
                                                          "plans": str(a.plans) if a.plans else None,
                                                          "secs": round(time.time() - t0)}, indent=1))
    print("ACTIVITY " + json.dumps({k: v for k, v in stats.items() if k != "furniture"}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
