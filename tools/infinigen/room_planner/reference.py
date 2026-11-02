"""Reference images -> venue spec (user 2026-10-16: one photo -> an image-generated multi-view of the same space -> the reference the
room is furnished from).

    python -m room_planner.reference --venue cafe IMG [IMG ...] --out spec.json        (run from tools/infinigen)

Claude (vision) reads the images and submits a spec through a tool call; every field is one of the knobs the pipeline already has, so
the spec drives them directly: wall finish + paint colour and floor (rematerial --style spec.json), counter front/top and back-bar
wood (proc_assets.STYLE), the fixture kind over the service, and a brief + must-have list for the planner (plan_scene --reference),
which also gets the images themselves. Cached by the images' sha256, like the plans.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from room_planner import catalog, client  # noqa: E402
from room_planner.styles import COUNTER_FRONTS, COUNTER_TOPS  # noqa: E402  (bpy-free)

MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def image_blocks(paths):
    return [{"type": "image", "source": {"type": "base64", "media_type": MEDIA[Path(p).suffix.lower()],
                                         "data": base64.b64encode(Path(p).read_bytes()).decode()}} for p in paths]


def image_ids(paths):
    return [hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16] for p in paths]


def spec_tool(venue):
    cats = sorted(k for k, v in catalog.FURNITURE.items() if venue in v["rooms"])
    return {
        "name": "submit_venue_spec",
        "description": "Submit what the reference space is made of, in the pipeline's own vocabulary.",
        "input_schema": {
            "type": "object",
            "required": ["brief", "wall", "floor", "counter_front", "counter_top", "backbar", "fixture", "must_have", "concept", "relations",
                         "architecture", "lighting", "density", "mood", "floor_tone", "table_top", "chair_style", "decor", "metal_finish"],
            "properties": {
                "brief": {"type": "string", "description": "3-5 sentences: the zones of the space and how they relate to the window, walls "
                                                           "and counter; the mood; what sits on the surfaces"},
                "wall": {"type": "string", "enum": ["paint", "brick", "concrete", "wood_panel", "tile"]},
                "wall_srgb": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
                              "description": "dominant wall colour, sRGB 0-1 (only for paint)"},
                "floor": {"type": "string", "enum": ["wood", "concrete", "tile"]},
                "counter_front": {"type": "string", "enum": sorted(COUNTER_FRONTS)},
                "counter_top": {"type": "string", "enum": sorted(COUNTER_TOPS)},
                "backbar": {"type": "string", "enum": ["walnut_slat", "oak_slat", "matte_black"]},
                "fixture": {"type": "string", "enum": ["pendant", "chandelier", "flush"]},
                "must_have": {"type": "array", "items": {"type": "object", "required": ["category", "count"], "properties": {
                    "category": {"type": "string", "enum": cats}, "count": {"type": "integer", "minimum": 1, "maximum": 20},
                    "where": {"type": "string"}}}},
                "mood": {"type": "string", "enum": ["bright_daylight", "warm_evening", "dark_moody"],
                         "description": "overall light: bright daylit / warm evening light with glowing fixtures / dark, low, candle-like"},
                "floor_tone": {"type": "string", "enum": ["pale", "medium", "dark"], "description": "floor lightness (pale oak, mid wood, dark wood)"},
                "floor_srgb": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3, "description": "dominant floor colour, sRGB 0-1"},
                "pendant_shade": {"type": "string", "enum": ["black_metal_dome", "white_enamel_dome", "brass_dome", "copper_dome", "glass_globe",
                                                             "fabric_drum", "bare_bulb"],
                                  "description": "the hanging lights over tables / counter, if any"},
                "upholstery_srgb": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
                                    "description": "colour of the main upholstery (banquette, upholstered chairs), sRGB 0-1; omit if none"},
                "table_top": {"type": "string", "enum": ["light_wood", "dark_wood", "white_stone", "black_stone", "butcher_block"]},
                "chair_style": {"type": "string", "enum": ["bentwood", "light_wood", "metal_bistro", "upholstered", "mixed"]},
                "decor": {"type": "array", "items": {"type": "string", "enum": ["framed_art", "hanging_plants", "potted_plants", "rugs", "candles",
                                                                               "flowers"]}},
                "concept": {"type": "string", "description": "the design concept in one sentence (what ties light, materials and furniture together)"},
                "relations": {"type": "array", "items": {"type": "string"}, "minItems": 3,
                              "description": "how the elements depend on each other, e.g. 'dark wood + low 2200K light + candles + dense seating = intimate'"},
                "architecture": {"type": "object", "required": ["ceiling", "feature_wall", "other_walls"], "properties": {
                    "ceiling": {"type": "string", "enum": ["plaster_white", "exposed_dark", "exposed_white", "timber_slats", "dark_painted"]},
                    "feature_wall": {"type": "string", "enum": ["brick", "wood_panel", "tile", "paint_dark", "paint_light", "concrete", "shelving"]},
                    "other_walls": {"type": "string", "enum": ["brick", "wood_panel", "tile", "paint_dark", "paint_light", "concrete"]},
                    "ducts_visible": {"type": "boolean"}}},
                "lighting": {"type": "object", "required": ["color_temp_k", "ambient", "daylight", "key_fixture"], "properties": {
                    "color_temp_k": {"type": "integer", "minimum": 2000, "maximum": 6000},
                    "ambient": {"type": "string", "enum": ["low", "medium", "high"], "description": "overall room brightness from fixtures"},
                    "daylight": {"type": "string", "enum": ["none", "low", "medium", "high"], "description": "light through the windows"},
                    "key_fixture": {"type": "string", "enum": ["pendant_row", "chandelier", "track_spots", "linear", "mixed"]},
                    "accents": {"type": "array", "items": {"type": "string", "enum": ["backbar_strip", "wall_sconces", "candles", "table_lamps",
                                                                                     "string_lights"]}}}},
                "metal_finish": {"type": "string", "enum": ["black", "brass", "chrome"]},
                "density": {"type": "object", "required": ["seats_per_10m2", "props_per_table", "plants"], "properties": {
                    "seats_per_10m2": {"type": "number", "minimum": 1, "maximum": 12},
                    "props_per_table": {"type": "number", "minimum": 0, "maximum": 6},
                    "plants": {"type": "integer", "minimum": 0, "maximum": 20}}},
                "not_reproducible": {"type": "string", "description": "what the pipeline has no asset for (people, laptops, the street)"},
            },
        },
    }


def _lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def read(paths, venue) -> dict:
    ids = image_ids(paths)
    key = "kit3-" + hashlib.sha256(json.dumps({"v": client.PROMPT_VERSION, "m": client.MODEL, "venue": venue, "ids": ids}).encode()).hexdigest()[:24]
    req = {
        "model": client.MODEL,
        "max_tokens": 3000,
        "system": [{"type": "text", "text": "You read interior reference photos (a real photo and/or an image-generated multi-view of the same "
                                            "space) and describe the space for a procedural furnishing pipeline as ONE coherent style kit: "
                                            "the architecture, light, materials, furniture family, density and decor of a design concept that "
                                            "belong together. Do not describe colours alone -- a style is the relation between its parts "
                                            "(e.g. dark wood needs low warm light, many small light sources and dense seating). Write those "
                                            "relations out. Pick the closest option for every field; list the furniture a viewer would miss if "
                                            "it were absent, with counts for the room in the photos. Return the spec by calling "
                                            "submit_venue_spec exactly once."}],
        "tools": [spec_tool(venue)],
        "tool_choice": {"type": "auto"} if client.MODEL in client.NO_FORCED_TOOL else {"type": "tool", "name": "submit_venue_spec"},
        "messages": [{"role": "user", "content": image_blocks(paths) + [{"type": "text", "text": f"Venue type: {venue}."}]}],
    }
    for attempt in range(3):                                     # the object fields came back as one string of leaked tool markup
        spec = dict(client._submit(req, key if attempt == 0 else f"{key}-r{attempt}", {"id": f"reference:{venue}"}, 0,
                                   tool="submit_venue_spec"))       # (warehouse_storage kit, 2026-10-16): re-ask, uncached
        if all(isinstance(spec.get(f), dict) for f in ("architecture", "lighting", "density")):
            break
    else:
        raise ValueError(f"reference kit for {venue}: architecture/lighting/density not objects after 3 tries")
    if spec.get("wall_srgb"):
        spec["wall_rgb"] = [round(_lin(c), 4) for c in spec["wall_srgb"]]
    if spec.get("floor_srgb"):
        spec["floor_rgb"] = [round(_lin(c), 4) for c in spec["floor_srgb"]]
    if spec.get("upholstery_srgb"):
        spec["upholstery_rgb"] = [round(_lin(c), 4) for c in spec["upholstery_srgb"]]
    spec["reference_ids"] = ids
    spec["venue"] = venue
    return spec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("--venue", required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    spec = read(a.images, a.venue)
    a.out.write_text(json.dumps({**spec, "images": [str(Path(p).resolve()) for p in a.images]}, indent=1, ensure_ascii=False))
    print("SPEC", json.dumps({k: spec[k] for k in ("wall", "floor", "counter_front", "counter_top", "fixture")}),
          [(m["category"], m["count"]) for m in spec.get("must_have", [])], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
