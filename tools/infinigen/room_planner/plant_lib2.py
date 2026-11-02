"""Placement from data/plant_library_v2 (Infinigen plants grown offline by plant_gen2.py; index.json lists them, entries with "skip" are dropped by the user/orchester).
    pick(slot, seed, i)  -> an index entry for a size class       load(entry, target_h, cap, max_w=None) -> a scaled, decimated, base-centred object (origin at its base, +Z up) or None
    plant(slot, seed, i, h=None, pot_rgb=None) -> a finished pot + plant object for floor/desk slots (None when the library is missing: callers fall back to the procedural plants)
Slots: floor (1.0-1.7 m), desk (0.3-0.5 m), atrium (trees 2.2-2.8 m, capped by hmax). Repeats of one model share its mesh data (linked duplicates)."""
import os
import json, random
from pathlib import Path
import bpy

LIB = Path("/jarvis/project/robomituba/data/plant_library_v2")
SLOTS = {                                                     # species allowed per slot
    "floor": ("fern", "snakeplant", "taromonocot", "bananamonocot", "agavemonocot"),      # green species only (no brown tussock / veratrum, no leafless bush)
    "desk": ("spiderplant", "snakeplant", "fern"),
    "atrium": ("bananamonocot",),                                         # tall accents only: leafpalmtree / plantbananatree are single fronds / leaves, not trees (O2 r18 A1/A3); the planter keeps its procedural palms as the tree layer
    "atrium_mid": ("taromonocot",),                                        # green taro only: the rust-brown veratrum / agave read as dead plants (O2 r18 A2)
    "atrium_under": ("fern", "snakeplant"),
}
#: seeds that read as healthy green plants (checked on the labelled sheets); a species not listed allows every seed
ALLOW = {"taromonocot": {2, 4, 6}, "bananamonocot": {4, 5, 6}, "agavemonocot": {4, 6}, "spiderplant": {1, 2, 3, 5}}
_cache = {}


def _index():
    if "idx" not in _cache:
        try:
            _cache["idx"] = [m for m in json.load(open(LIB / "index.json")) if not m.get("skip") and (LIB / m["file"]).exists()]
        except Exception:                                      # noqa: BLE001
            _cache["idx"] = []
    return _cache["idx"]


def available():
    return bool(_index())


def pick(slot, seed, i=0, kinds=None):
    ov = os.environ.get({"atrium": "ROOM_ATRIUM_SPECIES", "atrium_mid": "ROOM_ATRIUM_MID_SPECIES", "floor": "ROOM_FLOOR_PLANT_SPECIES", "desk": "ROOM_DESK_PLANT_SPECIES", "atrium_under": "ROOM_ATRIUM_UNDER_SPECIES"}.get(slot, ""))      # floor: O2 r21, the broad-leaf species (taro / banana / agave) read as flat polygon blades anywhere
    if ov:                                                    # O2 r20 AST-01: banana / taro leaves are single-sheet and read as flat polygon cut-outs at any cap -> 'none' drops the slot, or a comma list of other species
        if ov == "none":
            return None
        kinds = tuple(x for x in ov.split(",") if x)
    pool = [m for m in _index() if m["species"] in (kinds or SLOTS[slot]) and m["seed"] in ALLOW.get(m["species"], {m["seed"]})]
    if not pool:
        return None
    return random.Random(seed * 7919 + i).choice(pool)


def load(m, target_h, cap=60000, max_w=None, yaw=0.0):
    """Append the model, decimate to ~cap polys (cached per file so repeats share mesh data), scale uniformly to target_h (and under max_w wide), centre on its base."""
    cap = int(min(300000, cap * float(os.environ.get("ROOM_PLANT_CAP_X") or 1.0)))      # O2 r19 AST-01: banana / taro leaves decimated to 80k of 300k read as flat angular sheets; ROOM_PLANT_CAP_X=2.5 keeps ~2.5x the polygons (shared mesh data: one copy per model)
    key = (m["file"], cap)
    src = _cache.get(key)
    if src is None:
        try:
            with bpy.data.libraries.load(str(LIB / m["file"]), link=False) as (a, b):
                b.objects = [n for n in a.objects if n == "ir_plant"]
            o = b.objects[0]; bpy.context.scene.collection.objects.link(o)
            n = len(o.data.polygons)
            if n > cap:
                md = o.modifiers.new("ir_dec", "DECIMATE"); md.ratio = max(0.03, cap / n)
                bpy.context.view_layer.objects.active = o; bpy.ops.object.modifier_apply(modifier=md.name)
            bpy.context.scene.collection.objects.unlink(o)
            _cache[key] = src = o
        except Exception as e:                                 # noqa: BLE001
            print(f"[plant_lib2] {m['file']}: {e!r}"[:200]); return None
    o = bpy.data.objects.new(f"lib2_{m['species']}_{m['seed']}", src.data)       # a linked duplicate: same mesh data
    bpy.context.scene.collection.objects.link(o)
    sc = target_h / max(m["height"], 1e-3)
    if max_w:
        sc = min(sc, max_w / max(2 * m["radius"], 1e-3))
    o.scale = (sc, sc, sc); o.rotation_euler[2] = yaw
    return o


def plant(slot, seed, i=0, h=None, pot_rgb=None, cap=60000):
    from room_planner import proc_assets as pa
    m = pick(slot, seed, i)
    if m is None:
        return None
    r = random.Random(seed * 131 + i)
    h = h or (r.uniform(1.0, 1.7) if slot == "floor" else r.uniform(0.3, 0.5))
    pot_h = 0.4 if slot == "floor" else 0.13
    pot_rgb = pot_rgb or r.choice(((0.85, 0.83, 0.78), (0.6, 0.35, 0.22), (0.12, 0.12, 0.12), (0.7, 0.72, 0.68)))
    o = load(m, max(h - pot_h, 0.2), cap, max_w=0.95 if slot == "floor" else 0.34, yaw=r.uniform(0, 6.28))
    if o is None:
        return None
    o.location = (0, 0, pot_h - 0.02)
    pot = pa._flat(f"ir_pot_{int(pot_rgb[0] * 100)}", pot_rgb, 0.8)
    pr = (0.17, 0.22, 0.4) if slot == "floor" else (0.1, 0.13, 0.14)
    base = pa._prims(f"PlantLib2({slot},{i})", [(pot, [("cyl", (0, 0, pr[2] / 2), pr, (0, 0, 0))])])
    return pa._join_cloth(base, [o])
