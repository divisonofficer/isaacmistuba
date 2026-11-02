"""Object-realism pass on a generated Infinigen apartment (user 2026-10-13), after rematerial_rooms_infinigen2.py:

  1. clutter  -- every NatureShelfTrinkets (crystal/coral) goes; tableware off kitchen surfaces goes; each support plane keeps at most
                 one small object per 0.3 m of its width; survivors are squared to their support (yaw snapped to the parent's axes);
                 food bags lie on their face instead of standing.
  2. fabric   -- upholstery colours (Infinigen samples saturation 0.3-0.8, value 0.6-0.9) are replaced from a real-upholstery palette.
  3. art      -- WallArt canvases show CC0 paintings (data/wall_art_cc0, Art Institute of Chicago open access), centre-cropped to the
                 canvas; monitor/TV screens are switched off or show a painting, named ir_screen_* so the no-bake prep can turn their
                 emission off in the NIR band (an LCD emits next to no NIR).
  4. books    -- on bookcases a BookStack becomes a BookColumn (books standing in a row), and the shelf spots the trinkets held are
                 refilled with columns where the shelf has room.

Runs in the infinigen env (bpy as a module, Infinigen importable for BookColumnFactory):
    python tidy_objects_infinigen2.py IN.blend --out OUT.blend --solve-state solve_state.json [--seed 0]
"""
from __future__ import annotations

import argparse
import colorsys
import json
import os
import math
import random
import re
import time
from pathlib import Path

import bpy
from mathutils import Vector

REPO = Path(__file__).resolve().parents[2]
ART = REPO / "data/wall_art_cc0"
SHELVES = ("SimpleBookcaseFactory", "CellShelfFactory", "LargeShelfFactory", "SingleCabinetFactory")
KITCHEN = ("KitchenSpaceFactory", "KitchenCabinetFactory", "KitchenIslandFactory", "TableDiningFactory")
TABLEWARE = ("WineglassFactory", "CupFactory", "SpoonFactory", "KnifeFactory", "ForkFactory", "ChopsticksFactory", "PlateFactory",
             "BowlFactory", "PotFactory", "PanFactory")
UPHOLSTERED = ("SofaFactory", "BedFactory", "ArmChairFactory", "ChairFactory", "OttomanFactory", "BarChairFactory", "OfficeChairFactory")
FABRIC_MAT = re.compile(r"shader_(sofa_fabric|coarse_knit_fabric|fine_knit_fabric|velvet|leather)")
ART_MAT = re.compile(r"shader_(text|dark_art|art)\b")
#: sRGB hex, upholstery as sold: neutrals first, a few muted colours, leathers.
FABRIC = ["3b3d40", "55585b", "7a7c7e", "a3a29e", "c4c1b9", "cbbfa8", "b8a487", "ddd5c3", "8b7d6b", "2e3a4f", "56657a",
          "6b6a4a", "8a9a83", "3d4f42", "8c4f36", "9a7b4f", "b08c86", "5a4636"]
LEATHER = ["4a3528", "6b4430", "7a4a2b", "2b2522", "8c6a4f"]
PER_M = 1 / 0.3          # small objects kept per metre of support width


def lin(hexrgb: str) -> tuple:
    c = [int(hexrgb[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def jitter(rgb, rng, amount=0.06):
    h, s, v = colorsys.rgb_to_hsv(*rgb)
    return colorsys.hsv_to_rgb(h, s, min(1.0, v * (1 + rng.uniform(-amount, amount))))


def factory(name: str) -> str:
    return name.split("(")[0]


def tops():
    return [o for o in bpy.data.objects if ".spawn_asset(" in o.name and not (o.parent and ".spawn_asset(" in o.parent.name)]


def delete(o):
    for c in list(o.children_recursive) + [o]:
        bpy.data.objects.remove(c, do_unlink=True)


def zmin(o) -> float:
    return min((o.matrix_world @ Vector(c)).z for c in o.bound_box)


def span_along(o, parent) -> tuple:
    """o's extent along the parent's local y (a shelf's width axis)."""
    inv = parent.matrix_world.inverted()
    ys = [(inv @ (o.matrix_world @ Vector(c))).y for c in o.bound_box]
    return min(ys), max(ys)


def snap_yaw(o, parent):
    py = parent.rotation_euler.z
    k = round((o.rotation_euler.z - py) / (math.pi / 2))
    o.rotation_euler.z = py + k * math.pi / 2


# ---- 1 + 4: clutter and books -----------------------------------------------------------------------------------------------
def relations(solve_state: Path) -> dict:
    """blender name -> (support blender name, plane idx) for objects resting on a furniture support."""
    objs = json.loads(solve_state.read_text())["objs"]
    out = {}
    for rec in objs.values():
        for r in rec.get("relations", []):
            rel = r["relation"]
            parent = objs.get(r["target_name"], {})
            if rel.get("relation_type") == "StableAgainst" and "Subpart(support)" in rel.get("parent_tags", []) and parent.get("obj"):
                out[rec["obj"]] = (parent["obj"], r.get("parent_plane_idx", 0))
    return out


def tidy_clutter(rel: dict, rng: random.Random, stats: dict):
    by_name = {o.name: o for o in tops()}
    vacated = []                                    # (parent, plane, world xy, z) of removed shelf trinkets -> book spots
    groups = {}
    for name, o in list(by_name.items()):
        f = factory(name)
        parent_name, plane = rel.get(name, (None, None))
        parent = by_name.get(parent_name)
        pf = factory(parent_name) if parent_name else ""
        if f == "NatureShelfTrinketsFactory":
            if parent is not None and pf in SHELVES:
                vacated.append((parent, plane, o.matrix_world.translation.copy(), zmin(o)))
            delete(o); stats["trinkets_removed"] += 1
            continue
        if f in TABLEWARE and parent is not None and pf not in KITCHEN:
            delete(o); stats["tableware_off_kitchen_removed"] += 1
            continue
        if parent is not None and max(o.dimensions) < 0.5:
            groups.setdefault((parent.name, plane), []).append(o)
    for (pname, plane), objs in groups.items():
        parent = by_name[pname]
        cap = max(1, int(max(parent.dimensions[0], parent.dimensions[1]) * PER_M))
        objs.sort(key=lambda o: (not factory(o.name).startswith("Book"), rng.random()))
        for o in objs[cap:]:
            delete(o); stats["thinned"] += 1
        for o in objs[:cap]:
            snap_yaw(o, parent); stats["squared"] += 1
            if factory(o.name) == "FoodBagFactory":          # a bag of crisps lies on its face
                z0 = zmin(o)
                o.rotation_euler.x = math.pi / 2
                bpy.context.view_layer.update()
                o.location.z += z0 - zmin(o); stats["bags_laid_down"] += 1
    return by_name, vacated


def book_columns(by_name: dict, rel: dict, vacated: list, rng: random.Random, stats: dict):
    from infinigen.assets.objects.table_decorations import BookColumnFactory
    bpy.context.view_layer.update()
    alive = {o.name: o for o in tops()}
    taken = {}                                      # (parent, plane) -> [(y0, y1)] along the shelf width
    for name, o in alive.items():
        if name in rel and rel[name][0] in alive:
            parent = alive[rel[name][0]]
            taken.setdefault((parent.name, rel[name][1]), []).append(span_along(o, parent))
    spots = []
    for name, o in list(alive.items()):            # stacks on bookcases become columns
        if factory(name) == "BookStackFactory" and name in rel and factory(rel[name][0]) in SHELVES and rel[name][0] in alive:
            parent = alive[rel[name][0]]
            key = (parent.name, rel[name][1])
            taken[key] = [s for s in taken.get(key, []) if s != span_along(o, parent)]
            spots.append((parent, rel[name][1], o.matrix_world.translation.copy(), zmin(o)))
            delete(o); stats["stacks_to_columns"] += 1
    spots += vacated
    seed = rng.randrange(10 ** 6)
    for i, (parent, plane, xy, z) in enumerate(spots):
        fac = BookColumnFactory(seed + i)
        fac.n_books = rng.randint(7, 15)
        col = fac.spawn_asset(i)
        col.rotation_euler = (0, 0, parent.rotation_euler.z + math.pi / 2 * rng.choice((1, -1)))
        col.location = (xy.x, xy.y, 0)
        bpy.context.view_layer.update()
        col.location.z += z - zmin(col)
        bpy.context.view_layer.update()
        y0, y1 = span_along(col, parent)
        w = parent.dimensions[1] / 2 - 0.02
        key = (parent.name, plane)
        if y1 - y0 > 2 * w or any(a < y1 and y0 < b for a, b in taken.get(key, [])) or y0 < -w or y1 > w:
            delete(col); stats["column_spots_skipped"] += 1    # ponytail: no shuffling to make room; a skipped spot stays empty
            continue
        taken.setdefault(key, []).append((y0, y1))
        stats["columns_placed"] += 1


# ---- 2: fabric ---------------------------------------------------------------------------------------------------------------
def recolor_fabric(rng: random.Random, stats: dict, palette=None, leather=None):
    """palette/leather: the house's own subsets (activity pass); default the full lists."""
    mats = {s.material for o in tops() if factory(o.name) in UPHOLSTERED for ob in [o, *o.children_recursive]
            for s in getattr(ob, "material_slots", []) if s.material and FABRIC_MAT.match(s.material.name)}
    for m in mats:
        base = lin(rng.choice((leather or LEATHER) if "leather" in m.name else (palette or FABRIC)))
        nt = m.node_tree
        combines = [n for n in nt.nodes if n.bl_idname in ("ShaderNodeCombineColor", "ShaderNodeCombineRGB")]
        for j, n in enumerate(combines):
            rgb = jitter([c * (1 if j == 0 else rng.uniform(0.8, 1.1)) for c in base], rng)
            for sock, val in zip(list(n.inputs)[:3], rgb):
                if sock.is_linked and sock.links[0].from_node.bl_idname == "ShaderNodeValue":
                    sock.links[0].from_node.outputs[0].default_value = val
                elif not sock.is_linked:
                    sock.default_value = val
        for n in nt.nodes:
            if n.bl_idname == "ShaderNodeRGB":
                n.outputs[0].default_value = (*jitter(base, rng), 1.0)
        stats["fabric_materials"] += 1


# ---- 3: art and screens --------------------------------------------------------------------------------------------------------
def painting_material(name, img, face_lo, face_hi, emission=0.0, uv=False):
    """Base colour (or emission) from `img`, mapped on the canvas by object coordinates (canvas spans local y = width, z = height,
    seen from +x) and centre-cropped to the canvas aspect."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    w, h = face_hi[1] - face_lo[1], face_hi[2] - face_lo[2]
    a_img, a_can = img.size[0] / img.size[1], w / h
    su, sv = (a_can / a_img, 1.0) if a_img > a_can else (1.0, a_img / a_can)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["UV" if uv else "Object"], sep.inputs[0])     # uv: face_lo/hi are UV bounds in slots 1, 2
    def axis(sock, lo, size, s):
        m1 = nt.nodes.new("ShaderNodeMath"); m1.operation = "MULTIPLY_ADD"
        nt.links.new(sock, m1.inputs[0]); m1.inputs[1].default_value = s / size; m1.inputs[2].default_value = 0.5 - s * (lo + size / 2) / size
        return m1.outputs[0]
    comb = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(axis(sep.outputs["X" if uv else "Y"], face_lo[1], w, su), comb.inputs[0])
    nt.links.new(axis(sep.outputs["Y" if uv else "Z"], face_lo[2], h, sv), comb.inputs[1])
    tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = img; tex.extension = "EXTEND"
    nt.links.new(comb.outputs[0], tex.inputs[0])
    if emission > 0:
        bsdf.inputs["Base Color"].default_value = (0.01, 0.01, 0.01, 1)
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = emission
        bsdf.inputs["Roughness"].default_value = 0.08
    else:
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        bsdf.inputs["Roughness"].default_value = 0.5
    return m


def canvas_box(o, idx, axes=(1, 2)):
    me = o.data
    co = [me.vertices[v].co for p in me.polygons if p.material_index == idx for v in p.vertices]
    if not co:
        return None
    return [min(c[i] for c in co) for i in range(3)], [max(c[i] for c in co) for i in range(3)]


def hang_art(rng: random.Random, stats: dict, screens: bool = True):
    man = json.loads((ART / "manifest.json").read_text())["images"]
    # classical CC0 collections are full of nudes: not what a home's walls (or this dataset) should show
    nude = re.compile(r"nude|naked|bather|bathing|venus|odalisque|reclining|toilette|leda|susanna|danae|nymph|eve\b", re.I)
    pool = [r for r in man if not r.get("excluded") and not nude.search(r.get("title") or "")]   # manifest "excluded": reviewed
    if os.environ.get("ROOM_ART_POOL"):                         # generated venue prints instead of the CC0 paintings: ROOM_ART_POOL="art_wall,poster_shop" = prefixes of data/venue_refs/print_assets_v3/*.png
        from PIL import Image as _PI
        _d = REPO / "data/venue_refs/print_assets_v3"; _pre = tuple(x.strip() for x in os.environ["ROOM_ART_POOL"].split(",") if x.strip())
        _pl = []
        for _f in sorted(_d.glob("*.png")):
            if _f.name.startswith(_pre):
                with _PI.open(_f) as _im:
                    _pl.append({"file": str(_f), "aspect": _im.width / _im.height, "title": _f.stem})
        pool = _pl or pool
    rng.shuffle(pool)
    used = []
    def pick(aspect):
        best = min(pool, key=lambda r: abs(math.log(r["aspect"] / aspect)))
        pool.remove(best); used.append(best)
        return bpy.data.images.load(str(best["file"]) if os.path.isabs(best["file"]) else str(ART / best["file"]), check_existing=True)
    for o in tops():
        f = factory(o.name)
        if f not in ("WallArtFactory", "MonitorFactory", "TVFactory") or o.type != "MESH" or not pool or (not screens and f != "WallArtFactory"):
            continue
        screens = set()                             # tv.py marks the screen faces; its material is not always the Text print
        attr = o.data.attributes.get("screen") if f != "WallArtFactory" else None
        if attr is not None and attr.domain == "FACE":
            screens = {p.material_index for p, v in zip(o.data.polygons, attr.data) if v.value}
        for idx, slot in enumerate(o.material_slots):
            if not slot.material or not (ART_MAT.match(slot.material.name) or idx in screens):
                continue
            box = canvas_box(o, idx)
            if box is None:
                continue
            lo, hi = box
            if f == "WallArtFactory":
                img = pick((hi[1] - lo[1]) / max(hi[2] - lo[2], 1e-3))
                slot.material = painting_material(f"ir_painting_{stats['paintings']}", img, lo, hi)
                stats["paintings"] += 1
            else:                                   # screen: its own UV map (tv.py unwrap_faces + compute_uv_direction)
                uvl = o.data.uv_layers.active
                uvs = [uvl.data[li].uv for p in o.data.polygons if p.material_index == idx for li in p.loop_indices] if uvl else []
                if not uvs:
                    continue
                lo2 = [0, min(u.x for u in uvs), min(u.y for u in uvs)]; hi2 = [0, max(u.x for u in uvs), max(u.y for u in uvs)]
                if rng.random() < 0.5:
                    m = bpy.data.materials.new(f"ir_screen_off_{stats['screens']}"); m.use_nodes = True
                    b = m.node_tree.nodes["Principled BSDF"]
                    b.inputs["Base Color"].default_value = (0.01, 0.01, 0.012, 1); b.inputs["Roughness"].default_value = 0.06
                else:
                    img = pick(max(hi[0] - lo[0], hi[1] - lo[1]) / max(hi[2] - lo[2], 1e-3))
                    m = painting_material(f"ir_screen_{stats['screens']}", img, lo2, hi2, emission=1.5, uv=True)
                slot.material = m
                stats["screens"] += 1
    return used


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("blend")
    ap.add_argument("--out", required=True)
    ap.add_argument("--solve-state", required=True, type=Path)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    t0 = time.time()
    bpy.ops.wm.open_mainfile(filepath=a.blend)
    rng = random.Random(a.seed)
    stats = {k: 0 for k in ("trinkets_removed", "tableware_off_kitchen_removed", "thinned", "squared", "bags_laid_down",
                            "stacks_to_columns", "columns_placed", "column_spots_skipped", "fabric_materials", "paintings", "screens")}
    rel = relations(a.solve_state)
    by_name, vacated = tidy_clutter(rel, rng, stats)
    book_columns(by_name, rel, vacated, rng, stats)
    recolor_fabric(rng, stats)
    used = hang_art(rng, stats)
    bpy.ops.wm.save_as_mainfile(filepath=a.out, compress=True)
    Path(a.out + ".tidy.json").write_text(json.dumps({"stats": stats, "art": used, "seed": a.seed, "source": a.blend,
                                                      "secs": round(time.time() - t0)}, indent=1))
    print("TIDY " + json.dumps(stats), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
