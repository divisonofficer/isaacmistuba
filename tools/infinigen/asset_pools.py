"""Pools of scanned assets (ABO / HSSD / Poly Haven) that stand in for the A-tier procedural factories (docs/proc_assets_vs_scanned_pools_2026-10-17.md).

Not wired into furnish_rooms / realize yet (the orchester imports it when it chooses). No bpy: it reads the three index JSONs, so a
pool can be counted and inspected anywhere. An entry is the abo_assets dict (id, path, extent_m [x width, y HEIGHT, z depth], source ...),
so `abo_assets._import(entry, name)` and `abo_assets.pick(rng, pool)` take it as is (source shares apply across ABO / HSSD / PH).

    from asset_pools import pool
    entry = abo_assets.pick(rng, pool("steel_shelf"))
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path("/jarvis/project/robomituba")
INDEXES = (Path("/bean/ir_dataset/abo_v1/abo_object_index.json"), ROOT / "vendor_datasets/hssd_objects/hssd_object_index.json",
           ROOT / "vendor_datasets/polyhaven_models/polyhaven_object_index.json")
MAX_TRIANGLES = 300_000

# key -> filter. types: product_type in; cat: hssd_category in; ids: exact ids (Poly Haven ids are "PH_<Name>"); name: regex on name+id;
# need_name: the category match must also hit `name`; src: only these sources; not_name: regex that rejects; h / w / d: (min, max) metres of extent_m[1] / [0] / [2] (glTF Y is height).
SPECS = {
    "tall_plant": dict(name=r"banana tree|ficus|dracaena|palm|banyan|monstera|taro|rubber|bird of paradise|schefflera|yucca|fiddle|areca|alocasia|strelitzia", not_name=r"rose|lamp|blossom|cherry|christmas|wishing|fence|stump|mario|stand|bonaldo|bed|outdoor|parasol|umbrella|emilia|canopy|palmer|storage|king|queen|sofa|chair|bench|table", h=(1.3, 2.8), src=("hssd",)),      # O2 r23: tall tropical planting for the atrium (HSSD scanned potted plants)
    "steel_shelf": dict(ids=("PH_steel_frame_shelves_01", "PH_steel_frame_shelves_02", "PH_steel_frame_shelves_03", "PH_worn_metal_rack")),
    "locker": dict(types=("CABINET", "STORAGE_DRAWER"), cat=("cabinet", "wardrobe"), name=r"locker", need_name=True, not_name=r"drawer|cabinet door", h=(0.8, 2.2)),
    "chest_freezer": dict(cat=("fridge", "appliance", "kitchen_appliance"), name=r"freezer", need_name=True, not_name=r"fridge freezer|side by side|tall|upright", h=(0.7, 1.1)),
    "cash_register": dict(ids=("PH_CashRegister_01",)),
    "hand_truck": dict(ids=("PH_hand_truck",)),
    "clipboard": dict(ids=("PH_clipboard",)),
    "roller_shutter": dict(ids=("PH_rollershutter_door",)),
    "wash_basin": dict(cat=("sink", "sink_cabinet"), not_name=r"kitchen|double|farmhouse", w=(0.3, 0.9), h=(0.7, 1.2)),
    "towel": dict(cat=("towel",), not_name=r"mattress|comforter|duvet|blanket|bath ?mat|rug|woolly", h=(0.0, 0.35)),
    "trash_bin": dict(cat=("bin",), not_name=r"recycling station|compost", h=(0.3, 1.0)),
    "plastic_crate": dict(ids=("PH_plastic_crate_01", "PH_plastic_crate_02", "PH_plastic_crate_03", "PH_plastic_container")),
    "basket": dict(cat=("basket", "laundry_basket"), h=(0.1, 0.6)),
    "clothes_rack": dict(types=("CLOTHES_RACK",), h=(1.2, 2.0)),
    "exercise_mat": dict(types=("EXERCISE_MAT",)),
    "whiteboard": dict(types=("WRITING_BOARD",), cat=("board",), name=r"white ?board|dry.?erase|chalk|writing board", need_name=True, w=(0.6, 2.4)),
    "tv": dict(cat=("tv",), ids=("PH_Television_01", "PH_television_02"), w=(0.5, 1.8)),
    "chalkboard": dict(ids=("PH_standing_chalkboard_01",)),
    "ladder": dict(ids=("PH_ladder_sectioned_01", "PH_wooden_ladder", "PH_wooden_ladder_02")),
    "cart": dict(ids=("PH_industrial_storage_cart", "PH_tool_cart", "PH_portable_welding_cart")),
    "notebook": dict(ids=("PH_binder_notebook", "PH_office_notepads", "PH_stationery_supplies")),
    "cardboard_box": dict(ids=("PH_cardboard_box_01",)),
    "mirror": dict(types=("HOME_MIRROR",), h=(0.4, 2.0)),
    "hanging_plant": dict(name=r"hanging (plant|planter)|pothos", not_name=r"wall hanging planter", src=("hssd",)),
    "chandelier": dict(ids=("PH_Chandelier_01", "PH_Chandelier_02", "PH_Chandelier_03", "PH_chinese_chandelier", "PH_lantern_chandelier_01")),
}


def _inside(v, r):
    return r is None or r[0] <= v <= r[1]


@lru_cache(maxsize=1)
def _entries() -> tuple:
    out = []
    for p in INDEXES:
        if p.exists():
            out += [e for e in json.loads(p.read_text())["objects"] if e["triangles"] <= MAX_TRIANGLES]
    return tuple(out)


def pool(key: str) -> list:
    """Entries of every source that match SPECS[key]; empty when the key matches nothing."""
    s = SPECS[key]
    nm, bad = re.compile(s["name"], re.I) if "name" in s else None, re.compile(s["not_name"], re.I) if "not_name" in s else None
    res = []
    for e in _entries():
        text = f"{e['name']} {e['id']}"
        by_id = e["id"] in s.get("ids", ())
        by_attr = (e["product_type"] in s.get("types", ()) or e.get("hssd_category") in s.get("cat", ())
                   or (nm is not None and not s.get("types") and not s.get("cat") and nm.search(text)))
        if not (by_id or by_attr):
            continue
        if not by_id and s.get("need_name") and not nm.search(text):
            continue
        if not by_id and s.get("src") and e.get("source", "abo") not in s["src"]:
            continue
        if bad is not None and bad.search(text):
            continue
        x, y, z = e["extent_m"]
        if by_id or (_inside(y, s.get("h")) and _inside(x, s.get("w")) and _inside(z, s.get("d"))):
            res.append(e)
    return res


if __name__ == "__main__":
    import collections
    for k in SPECS:
        p = pool(k)
        print(f"{k:15s} n={len(p):4d} {dict(collections.Counter(e.get('source', 'abo') for e in p))}  e.g. {[(e['name'] or e['id'])[:28] for e in p[:2]]}")
