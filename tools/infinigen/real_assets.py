"""Real models for the kit-stage shells instead of box primitives (user 2026-10-25: 'no boxy stand-ins, realistic high-poly modelling';
'products from the asset library, broadly'). Used by hotel5_shell / h2_ref / liq_shell / conv_shell / parking_lobby.

  abo(kind, seed, x, y, z, yaw, fit=None)   an ABO / HSSD / Poly Haven model from furnish_rooms.pool(kind) or POOLS below, its front (ABO -y) turned to `yaw`,
                                            base on z, footprint centred on (x, y); fit = (max length, max depth, max height) scales it down uniformly to fit
  lib(name, seed, x, y, z, yaw=0, k=1.0)    an object_library_v2 small object (lib_objects.MAP name: PlateFactory, WineglassFactory, CupFactory, BowlFactory,
                                            PanFactory, PotFactory, VaseFactory, FoodBoxFactory, BottleFactory, LibTowelFactory ...), base on z, scaled by k
  inf(src, seed, x, y, z, yaw=0, fit=None)  an Infinigen factory through realize._cls (e.g. "inf:BlanketFactory")
Each returns the object or None (the caller then keeps its old primitive); STATS counts spawned / failed per kind.
"""
from __future__ import annotations

import math
import random

import bpy
from mathutils import Matrix, Vector

STATS = {}
ABO_FRONT = (0.0, -1.0)
_POOLS = {}
_RECOL = {}


def _extra_pool(kind):
    import furnish_rooms as fr
    P = fr._pool
    spec = {"barrel": lambda: P(("CHAIR", "SOFA"), w=(0.6, 0.95), d=(0.6, 0.95), h=(0.65, 0.95), name=lambda e: "barrel" in e["name"].lower() or "accent" in e["name"].lower() or "club" in e["name"].lower()),
            "loungesofa": lambda: P(("SOFA",), w=(2.0, 3.2), d=(0.8, 1.2), h=(0.65, 0.95)),
            "roundtable": lambda: P(("TABLE",), w=(0.7, 1.2), d=(0.7, 1.2), h=(0.35, 0.55), name=lambda e: "round" in e["name"].lower()),
            "bench": lambda: P(("BENCH",), w=(1.0, 2.0), h=(0.35, 0.9)),
            "bed": lambda: P(("BED",), w=(1.35, 2.0), d=(1.9, 2.4), h=(0.7, 1.5)),
            "tablelamp": lambda: P(("LAMP",), w=(0.15, 0.5), d=(0.15, 0.5), h=(0.35, 0.75)),
            "planter": lambda: P(("PLANTER",), h=(0.6, 1.9)),
            "smallplant": lambda: P(("PLANTER",), h=(0.2, 0.55)),
            "pillow": lambda: P(("PILLOW",), w=(0.35, 0.7), h=(0.3, 0.7)),
            "bigrug": lambda: P(("RUG",), w=(2.2, 3.6), d=(1.6, 3.0), h=(0.0, 0.05)),
            "wallart": lambda: P(("WALL_ART",), w=(0.5, 1.2), h=(0.5, 1.2)),
            "deskchair": lambda: P(("CHAIR",), w=(0.45, 0.7), d=(0.45, 0.7), h=(0.75, 1.0), name=lambda e: "dining" in e["name"].lower() or "side chair" in e["name"].lower() or "upholster" in e["name"].lower()),
            "console": lambda: P(("TABLE", "CABINET"), w=(1.2, 2.0), d=(0.28, 0.55), h=(0.7, 0.95), name=lambda e: "console" in e["name"].lower() or "sofa table" in e["name"].lower() or "entryway" in e["name"].lower()),
            "sidetable": lambda: P(("TABLE",), w=(0.35, 0.6), d=(0.35, 0.6), h=(0.45, 0.7)),
            "wastebin": lambda: P(("HOME_FURNITURE_AND_DECOR", "STORAGE_BOX"), w=(0.25, 0.5), d=(0.25, 0.5), h=(0.45, 0.9), name=lambda e: "trash" in e["name"].lower() or "waste" in e["name"].lower())}
    hs = {"suitcase": (("HSSD_CASE",), None, (0.35, 0.9)), "bag": (("HSSD_BAG",), None, (0.25, 0.7)), "shoes": (("HSSD_SHOE",), r"sneaker|shoe|loafer|boot|trainer", (0.2, 0.4)),
          "laptop": (("HSSD_LAPTOP",), None, (0.25, 0.45)), "phone": (("HSSD_PHONE",), r"smart|iphone|galaxy|mobile|cell", (0.06, 0.2)), "tray": (("HSSD_TRAY",), None, (0.3, 0.65)),
          "mug": (("HSSD_CUP",), r"mug|cup", (0.06, 0.16)), "book": (("HSSD_BOOK",), None, (0.15, 0.32)), "towel": (("HSSD_TOWEL",), None, (0.25, 0.7)),
          "luggagerack": (None, r"luggage rack", (0.45, 0.9)),
          "vanity": (("HSSD_SINK_CABINET", "HSSD_BATH_SINK", "CABINET"), r"vanity|basin|sink", (0.9, 1.7)),
          "notepad": (("HSSD_STACK_OF_PAPERS", "HSSD_BOOK"), r"paper|note|pad|journal|diary", (0.12, 0.35)),
          "tv": (("HSSD_TV",), None, (0.9, 1.6)),
          "credenza": (("CABINET", "HSSD_TV_STAND"), r"media|console|sideboard|credenza|tv stand", (1.2, 2.2)),
          "chandelier": (("LAMP", "LIGHT_FIXTURE"), r"chandelier", (0.6, 1.4)),
          "napkin": (("HSSD_TOWEL",), r"napkin", (0.15, 0.45)),
          "barcart": (("TABLE",), r"bar cart|trolley|serving cart", (0.6, 1.1)),
          "extinguisher": (None, r"fire extinguisher", (0.4, 0.8)),
          "bouquet": (("VASE", "PLANTER", "HSSD_FLOWER_STAND", "HOME_FURNITURE_AND_DECOR"), r"rose|bouquet|flower|orchid|tulip|peony|hydrangea|lil(y|ies)", (0.25, 0.75))}
    if kind in hs:                                            # HSSD guest belongings (no luggage / shoes / laptops in ABO)
        types, rx, (mn, mx) = hs[kind]
        import json
        import re
        if "hssd" not in _POOLS:                              # HSSD + Poly Haven indexes (the abo_assets pool only holds them when ROOM_EXTRA_ASSET_INDEXES says so)
            _POOLS["hssd"] = json.load(open("/jarvis/project/robomituba/vendor_datasets/hssd_objects/hssd_object_index.json"))["objects"] + \
                json.load(open("/jarvis/project/robomituba/vendor_datasets/polyhaven_models/polyhaven_object_index.json"))["objects"]
        import abo_assets
        return [e for e in _POOLS["hssd"] if (types is None or e["product_type"] in types) and (rx is None or re.search(rx, e["name"], re.I)) and mn <= max(e["extent_m"]) <= mx
                and e["triangles"] <= abo_assets.MAX_TRIANGLES and not e.get("emissive_materials")]
    f = spec.get(kind)
    return f() if f else fr.pool(kind)


def _pool(kind):
    if kind not in _POOLS:
        try:
            _POOLS[kind] = _extra_pool(kind) or []
        except Exception as ex:                               # noqa: BLE001 -- not cached: one transient failure must not disable the kind for the whole process (asset QA rev2 R3)
            print(f"[real_assets] pool {kind!r} failed: {ex!r}", flush=True)
            return []
    return _POOLS[kind]


_MISSED = set()


def _count(kind, ok, why=""):
    s = STATS.setdefault(kind, [0, 0]); s[0 if ok else 1] += 1
    if not ok and kind not in _MISSED:                        # loud, once per kind: a silent None made bottles / packs vanish (asset QA rev2 R1/R2)
        _MISSED.add(kind); print(f"[real_assets] MISS {kind} {why}-> caller fallback", flush=True)


def report(stats, prefix):
    """Copy the spawn / miss counts into a shell's kit stats (asset QA rev2 R8: liq / conv never exported them)."""
    stats[f"{prefix}_real_assets"] = {k: list(v) for k, v in STATS.items()}
    stats[f"{prefix}_real_assets_missed"] = sorted(k for k, v in STATS.items() if v[1])


def _stand(o, x, y, z, rz, fit, grow=False):
    """Upright at (x, y) with yaw rz, base on z; fit scales down uniformly so the extents fit (L, D, H). Pure matrix maths on the local box: no view-layer update (a full update per object cost seconds on a 475 MB floor)."""
    pts = [Vector(c) for c in o.bound_box]
    ext = [max(p[i] for p in pts) - min(p[i] for p in pts) for i in range(3)]
    k = 1.0
    if fit:
        k = min(*(f / max(v, 1e-4) for f, v in zip(fit, ext) if f), *(() if grow else (1.0,)))
    R = Matrix.Rotation(rz, 3, "Z") @ Matrix.Diagonal((k, k, k))
    q = [R @ p for p in pts]
    cx, cy, zb = (min(p.x for p in q) + max(p.x for p in q)) / 2, (min(p.y for p in q) + max(p.y for p in q)) / 2, min(p.z for p in q)
    o.rotation_mode = "XYZ"; o.rotation_euler = (0, 0, rz); o.scale = (k, k, k)
    o.location = (x - cx, y - cy, z - zb + 0.002)
    return o


def top(o):
    """World top z of an object placed by _stand / lib (location + scaled local box; valid before any view-layer update)."""
    return o.location.z + o.scale.z * max(c[2] for c in o.bound_box)


def soft(name, mat, cx, cy, cz, sx, sy, sz, yaw=0.0, seed=0, puff=0.6, lump=0.006):
    """Shared soft-goods helper (H2 + H5 pillows, cushions, mattress tops): a subdivided box whose height is inflated toward the centre and pinched at the seams
    (pillow profile), a little random lumpiness, Subdivision level 2 + smooth shading: rounded, no sharp corners."""
    import bmesh
    rg = random.Random(seed); bm = bmesh.new(); r = bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=6, use_grid_fill=True)
    ph = [rg.uniform(0, 6.3) for _ in range(3)]
    for v in bm.verts:
        x, y, z = v.co                                         # unit cube -0.5..0.5
        fx, fy = max(0.0, 1 - (2 * abs(x)) ** 2), max(0.0, 1 - (2 * abs(y)) ** 2)
        k = (fx * fy) ** puff                                   # 1 at the centre, 0 at the seam
        v.co.x, v.co.y = x * sx, y * sy
        v.co.z = z * sz * (0.25 + 0.75 * k) + (lump * (math.sin(x * 9 + ph[0]) * math.sin(y * 7 + ph[1])) if z > 0 else 0.0)
    if yaw:
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(yaw, 3, "Z"), verts=bm.verts)
    bmesh.ops.translate(bm, vec=(cx, cy, cz), verts=bm.verts)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free(); me.materials.append(mat)
    for p in me.polygons:
        p.use_smooth = True
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    sub = o.modifiers.new("sub", "SUBSURF"); sub.levels = 2; sub.render_levels = 2
    return o


def drape(name, mat, x0, x1, y0, y1, ztop, hang, along_x, thick=0.05, seed=0):
    """A cloth that lies on the bed top (x0..x1 / y0..y1) and hangs `hang` m over the two long sides (across the bed axis) with a soft rolled edge and gentle folds."""
    import bmesh
    rg = random.Random(seed); bm = bmesh.new()
    nu, nv = 24, 16
    L_ = (x1 - x0) if along_x else (y1 - y0); W_ = (y1 - y0) if along_x else (x1 - x0)
    prof = []                                                       # (across, z) profile: down one side, over the top, down the other
    for k in range(nv + 1):
        t = k / nv
        if t < 0.15:
            a = -W_ / 2 - 0.02 + 0.04 * (t / 0.15) ** 2; z = ztop - hang * (1 - t / 0.15) ** 1.4
        elif t > 0.85:
            a = W_ / 2 + 0.02 - 0.04 * ((1 - t) / 0.15) ** 2; z = ztop - hang * (1 - (1 - t) / 0.15) ** 1.4
        else:
            a = -W_ / 2 + W_ * (t - 0.15) / 0.7; z = ztop + 0.015 * math.sin(math.pi * (t - 0.15) / 0.7)
        prof.append((a, z))
    ph = rg.uniform(0, 6.3); grid = []
    for i in range(nu + 1):
        u = -L_ / 2 + L_ * i / nu; row = []
        for a, z in prof:
            dz = 0.008 * math.sin(u * 11 + ph) * math.cos(a * 6)          # straight hem (r23 review: the edge ripple read as a wavy hem)
            x, y = (u, a) if along_x else (a, u)
            row.append(bm.verts.new(((x0 + x1) / 2 + x, (y0 + y1) / 2 + y, z + dz)))
        grid.append(row)
    for i in range(nu):
        for k in range(nv):
            bm.faces.new((grid[i][k], grid[i + 1][k], grid[i + 1][k + 1], grid[i][k + 1]))
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free(); me.materials.append(mat)
    for p in me.polygons:
        p.use_smooth = True
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    s = o.modifiers.new("thick", "SOLIDIFY"); s.thickness = thick; s.offset = 1.0
    return o


def abo(kind, seed, x, y, z, yaw, fit=None):
    pool = _pool(kind)
    if not pool:
        _count(kind, False); return None
    import abo_assets
    try:
        e = abo_assets.pick(random.Random(seed), pool)
        o = abo_assets._import(e, f"Real_{kind}({e['id']})")
    except Exception:                                         # noqa: BLE001
        _count(kind, False); return None
    _count(kind, True)
    return _stand(o, x, y, z, yaw - math.atan2(ABO_FRONT[1], ABO_FRONT[0]), fit)


def hssd(rx, seed, x, y, z, yaw, fit=None, cats=None, size=(0.0, 99.0), grow=False):
    """An HSSD / Poly Haven model whose name or id matches regex `rx` (optionally hssd_category in `cats`, max extent within `size`), placed like abo().
    grow=True lets `fit` scale UP as well (a slot to fill, e.g. a wine-rack cabinet stacked to a 1.8 m bay)."""
    import re
    key = f"hssd:{rx}:{cats}:{size}"
    if key not in _POOLS:
        try:
            import json
            if "hssd" not in _POOLS:
                _POOLS["hssd"] = json.load(open("/jarvis/project/robomituba/vendor_datasets/hssd_objects/hssd_object_index.json"))["objects"] + \
                    json.load(open("/jarvis/project/robomituba/vendor_datasets/polyhaven_models/polyhaven_object_index.json"))["objects"]
            _POOLS[key] = [e for e in _POOLS["hssd"] if re.search(rx, f"{e['name']} {e['id']}", re.I) and (cats is None or e.get("hssd_category") in cats)
                           and size[0] <= max(e["extent_m"]) <= size[1] and e["triangles"] <= 300_000]
        except Exception as ex:                               # noqa: BLE001
            print(f"[real_assets] hssd pool {rx!r} failed: {ex!r}", flush=True); _count(key, False); return None
    pool = _POOLS[key]
    if not pool:
        _count(key, False, "(empty pool) "); return None
    import abo_assets
    try:
        e = random.Random(seed).choice(pool)
        o = abo_assets._import(e, f"Real_hssd({e['id']})")
    except Exception as ex:                                   # noqa: BLE001
        _count(key, False, f"({ex!r}) "); return None
    _count(key, True)
    return _stand(o, x, y, z, yaw - math.atan2(ABO_FRONT[1], ABO_FRONT[0]), fit, grow)


SIZE_CAP = (("pineapple", 0.30), ("coconut", 0.18), ("fruitcontainer", 0.35), ("fruit", 0.12), ("apple", 0.10), ("strawberry", 0.05), ("blackberry", 0.03),
            ("wineglass", 0.25), ("bottle", 0.35), ("cup", 0.15), ("can", 0.20), ("jar", 0.25), ("foodbox", 0.40), ("foodbag", 0.40), ("plate", 0.30), ("bowl", 0.30),
            ("pan", 0.50), ("pot", 0.45), ("lid", 0.35), ("fork", 0.22), ("knife", 0.25), ("spoon", 0.22), ("chopstick", 0.25), ("spatula", 0.35), ("vase", 0.50),
            ("towel", 0.70), ("book", 0.40))       # max extent (m) per library kind, first substring match wins; anything else 0.5 (small decor)


def size_cap(name):
    n = name.lower()
    return next((c for key, c in SIZE_CAP if key in n), 0.5)


def lib(name, seed, x, y, z, yaw=0.0, k=1.0, mat=None):
    from room_planner import lib_objects
    try:
        F = lib_objects.factory(name)
        o = F(seed).spawn_asset(0) if F else None
    except Exception:                                         # noqa: BLE001
        o = None
    if o is None:
        _count(name, False); return None
    _count(name, True)
    ext = max(o.dimensions) if o.type == "MESH" else 0.0
    cap = size_cap(name)                                      # every library prop clamped to its size class (S37 r12 / r16: fruit and packs came in at 2-8 m)
    if ext * k > cap:
        k = cap / ext; _count(name + "_clamped", True)
    if k != 1.0:
        o.scale = (k, k, k)
    if mat is not None:                                       # e.g. white banquet china instead of the library's coloured plates (one copy per material, shared)
        key = (o.data.name, mat.name); me = _RECOL.get(key)
        if me is None:
            me = o.data.copy(); me.materials.clear(); me.materials.append(mat); [setattr(p_, "material_index", 0) for p_ in me.polygons]; _RECOL[key] = me
        o.data = me
    o.rotation_mode = "XYZ"; o.rotation_euler = (0, 0, yaw); o.location = (x, y, z)
    return o


def inf(src, seed, x, y, z, yaw=0.0, fit=None):
    try:
        from room_planner import realize
        o = realize._cls(src)(seed).spawn_asset(0)
    except Exception:                                         # noqa: BLE001
        o = None
    if o is None:
        _count(src, False); return None
    _count(src, True)
    return _stand(o, x, y, z, yaw, fit)


if __name__ == "__main__":                                  # blender -b -P real_assets.py: smoke test of every pool
    import sys
    sys.path[:0] = ["/jarvis/project/robomituba/tools/infinigen"]
    for i, kd in enumerate(("sofa", "loungesofa", "barrel", "roundtable", "coffee", "armchair", "nightstand", "tablelamp", "floorlamp", "planter", "smallplant", "pillow", "bigrug", "rug", "bench", "wallart", "deskchair", "desk", "wastebin")):
        o = abo(kd, 3, i * 3.0, 0, 0, 0.0)
        print("RA", kd, len(_pool(kd)), o and [round(v, 2) for v in o.dimensions])
    for i, nm in enumerate(("PlateFactory", "WineglassFactory", "CupFactory", "BowlFactory", "PanFactory", "PotFactory", "VaseFactory", "FoodBoxFactory", "LibTowelFactory")):
        o = lib(nm, 5, i, 5, 0)
        print("RL", nm, o and [round(v, 3) for v in o.dimensions])
    o = inf("inf:BlanketFactory", 2, 0, 9, 0); print("RI blanket", o and [round(v, 2) for v in o.dimensions])
    assert STATS, "nothing spawned"
    assert size_cap("LibAppleFactory") == 0.10 and size_cap("BottleFactory") == 0.35 and size_cap("LibFruitFactory") == 0.12 and size_cap("Whatever") == 0.5
