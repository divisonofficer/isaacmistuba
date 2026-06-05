"""
Phase 2: Create a clean new scene from the moorelane Kitchen hierarchy.

Extracts all objects under /ROOT/Kitchen/ from office_lobby_001 authoring_map
(which already has correct metre-space coordinates from the original USD import),
computes the room bounds for the kitchen area, and writes a fresh scene directory.

Usage:
  python apps/import_moorelane_kitchen.py \
      --source-project opticalnav-v0.2 \
      --source-scene office_lobby_001 \
      --output-project opticalnav-v0.2 \
      --output-scene moorelane_kitchen_001

  # Or rebuild editor_geometry fresh from USD (requires pxr):
  python apps/import_moorelane_kitchen.py --rebuild-editor-geometry
"""

import argparse
import json
import math
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OPTICALNAV_ROOT = REPO_ROOT / "out" / "opticalnav"

MOORELANE_USD_REF = (
    "assets/moorelane/Intel_mooreLane_v1_2_0/"
    "Intel_mooreLane/USD/4004MooreLane_ASWF_publish3.usda"
)

# Category → authoring_map type mapping
CATEGORY_TO_TYPE: dict[str, str] = {
    "glass": "glass_wall",
    "mirror": "mirror_wall",
    "wall": "wall",
    "floor": "landmark",
    "furniture": "landmark",
    "object": "landmark",
    "shell": "landmark",
}

# label/path hints → specific types
def _infer_type(label: str, source_path: str) -> str:
    label_l = label.lower()
    path_l = source_path.lower()
    if any(k in label_l or k in path_l for k in ("chair", "seat", "stool", "barstool")):
        return "chair"
    if any(k in label_l or k in path_l for k in ("table", "desk", "counter", "bench", "shelf")):
        return "table"
    if any(k in label_l or k in path_l for k in ("plant", "tree", "planter", "fern", "palm", "basil", "herb")):
        return "plant"
    if any(k in label_l or k in path_l for k in ("glass", "window", "glazing")):
        return "glass_wall"
    return "landmark"


def _margin(lo: float, hi: float, pct: float = 0.08) -> tuple[float, float]:
    span = hi - lo
    pad = max(0.5, span * pct)
    return lo - pad, hi + pad


def build_kitchen_authoring_map(
    source_am: dict,
    scene_id: str,
    *,
    prim_root: str = "/ROOT/Kitchen",
) -> dict:
    source_objects = source_am.get("objects") or []

    kitchen_objects = [
        o for o in source_objects
        if prim_root in (o.get("source_ref") or "")
    ]

    # Compute 2D bounding box
    xs = [o["geometry"]["center"][0] for o in kitchen_objects if o.get("geometry", {}).get("center")]
    ys = [o["geometry"]["center"][1] for o in kitchen_objects if o.get("geometry", {}).get("center")]
    if not xs:
        raise ValueError(f"No objects found under {prim_root}")

    x_lo, x_hi = _margin(min(xs), max(xs))
    y_lo, y_hi = _margin(min(ys), max(ys))
    map_w = math.ceil(x_hi - x_lo)
    map_h = math.ceil(y_hi - y_lo)

    # Offset objects so room starts near (0,0)
    x_off = x_lo
    y_off = y_lo

    new_objects = []
    for obj in kitchen_objects:
        geom = dict(obj.get("geometry") or {})
        center = geom.get("center")
        if center:
            geom["center"] = [round(center[0] - x_off, 4), round(center[1] - y_off, 4)]

        source_ref = obj.get("source_ref") or ""
        prim_path = source_ref.split("#", 1)[1] if "#" in source_ref else ""
        usd_ref = source_ref.split("#", 1)[0] if "#" in source_ref else ""

        new_obj: dict = {
            "id": obj["id"],
            "type": _infer_type(obj.get("label") or "", prim_path),
            "label": obj.get("label") or obj["id"],
            "placement": obj.get("placement") or "point",
            "geometry": geom,
            "material": obj.get("material") or "default",
            "source_ref": source_ref,
            "navigation": obj.get("navigation") or {
                "blocks_navigation": False,
                "hazard_type": None,
                "include_in_hazard_mask": False,
                "instruction_candidate": False,
                "goal_candidate": False,
            },
            "metadata": {
                "asset_source_path": prim_path,
                "usd_ref": usd_ref,
                **(obj.get("metadata") or {}),
            },
            "is_emitter": obj.get("is_emitter", False),
            "emitter_radiance": obj.get("emitter_radiance"),
            "emitter_intensity": obj.get("emitter_intensity", 1.0),
        }
        new_objects.append(new_obj)

    am = {
        "scene_id": scene_id,
        "version": "opticalnav-authoring-map-v0.2",
        "unit": "meter",
        "floorplan_ref": None,
        "objects": new_objects,
        "regions": [
            {
                "id": "traversable_001",
                "type": "traversable",
                "label": "Kitchen floor",
                "placement": "rectangle",
                "geometry": {
                    "type": "rectangle",
                    "center": None,
                    "yaw_deg": 0.0,
                    "pitch_deg": 0.0,
                    "roll_deg": 0.0,
                    "start": None,
                    "end": None,
                    "bounds": [0.5, 0.5, round(map_w - 0.5, 2), round(map_h - 0.5, 2)],
                    "height_m": None,
                    "thickness_m": None,
                    "size_m": None,
                    "base_height_m": 0.0,
                    "scale": None,
                    "extras": {},
                },
                "navigation": {
                    "blocks_navigation": False,
                    "hazard_type": None,
                    "include_in_hazard_mask": False,
                    "instruction_candidate": False,
                    "goal_candidate": False,
                },
                "metadata": {},
            },
            {
                "id": "goal_001",
                "type": "goal",
                "label": "Kitchen exit",
                "placement": "rectangle",
                "geometry": {
                    "type": "rectangle",
                    "center": None,
                    "yaw_deg": 0.0,
                    "pitch_deg": 0.0,
                    "roll_deg": 0.0,
                    "start": None,
                    "end": None,
                    "bounds": [
                        round(map_w - 1.5, 2), round(map_h - 1.5, 2),
                        round(map_w - 0.3, 2), round(map_h - 0.3, 2),
                    ],
                    "height_m": None,
                    "thickness_m": None,
                    "size_m": None,
                    "base_height_m": 0.0,
                    "scale": None,
                    "extras": {},
                },
                "navigation": {
                    "blocks_navigation": False,
                    "hazard_type": None,
                    "include_in_hazard_mask": False,
                    "instruction_candidate": False,
                    "goal_candidate": True,
                },
                "metadata": {},
            },
        ],
        "materials": (source_am.get("materials") or []),
        "environment": source_am.get("environment") or {
            "mode": "constant",
            "envmap_ref": None,
            "radiance": [0.8, 0.8, 0.85],
            "intensity": 1.0,
            "rotation_deg": 0.0,
            "background_visible": True,
        },
        "camera_rig": source_am.get("camera_rig") or {
            "rig_id": "mobile_base_default",
            "base_frame": "base_link",
            "sensors": [],
        },
        "settings": {
            "grid_size_m": 0.25,
            "default_wall_height_m": 2.7,
            "default_wall_thickness_m": 0.08,
            "map_w": map_w,
            "map_h": map_h,
        },
        "metadata": {
            "created_from": "import_moorelane_kitchen.py",
            "source_scene": "office_lobby_001",
            "prim_root": prim_root,
            "usd_ref": MOORELANE_USD_REF,
        },
    }
    return am


def main() -> None:
    parser = argparse.ArgumentParser(description="Create kitchen-only scene from moorelane USD")
    parser.add_argument("--source-project", default="opticalnav-v0.2")
    parser.add_argument("--source-scene", default="office_lobby_001")
    parser.add_argument("--output-project", default="opticalnav-v0.2")
    parser.add_argument("--output-scene", default="moorelane_kitchen_001")
    parser.add_argument("--prim-root", default="/ROOT/Kitchen",
                        help="USD prim path root to filter (default: /ROOT/Kitchen)")
    parser.add_argument("--rebuild-editor-geometry", action="store_true",
                        help="Re-extract editor_geometry.json from USD (requires pxr)")
    args = parser.parse_args()

    src_am_path = (
        OPTICALNAV_ROOT / args.source_project / "scenes" / args.source_scene / "authoring_map.json"
    )
    if not src_am_path.exists():
        raise FileNotFoundError(f"Source authoring_map not found: {src_am_path}")

    source_am = json.loads(src_am_path.read_text(encoding="utf-8"))

    out_scene_dir = OPTICALNAV_ROOT / args.output_project / "scenes" / args.output_scene
    out_scene_dir.mkdir(parents=True, exist_ok=True)

    print(f"Building {args.output_scene} from {args.source_scene} prim_root={args.prim_root}")
    am = build_kitchen_authoring_map(source_am, args.output_scene, prim_root=args.prim_root)

    out_am_path = out_scene_dir / "authoring_map.json"
    out_am_path.write_text(json.dumps(am, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Wrote authoring_map.json  objects={len(am['objects'])}")
    print(f"  Room size: {am['settings']['map_w']} × {am['settings']['map_h']} m")

    # Copy / symlink editor_geometry.json from source (contains all moorelane bounds)
    src_eg = (
        OPTICALNAV_ROOT / args.source_project / "scenes" / args.source_scene / "editor_geometry.json"
    )
    if src_eg.exists():
        import shutil
        dst_eg = out_scene_dir / "editor_geometry.json"
        shutil.copy2(src_eg, dst_eg)
        print(f"  Copied editor_geometry.json from source scene")

    if args.rebuild_editor_geometry:
        import sys
        sys.path.insert(0, str(REPO_ROOT / "modules" / "mitsuba_converter" / "src"))
        from mitsuba_converter.usd_editor_geometry import build_usd_editor_geometry
        usd_path = REPO_ROOT / MOORELANE_USD_REF
        print(f"  Rebuilding editor_geometry from USD (may be slow)...")
        eg = build_usd_editor_geometry(usd_path, scene_id=args.output_scene, usd_ref=MOORELANE_USD_REF)
        eg_path = out_scene_dir / "editor_geometry.json"
        eg_path.write_text(json.dumps(eg, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  Rebuilt editor_geometry.json  objects={len(eg.get('objects', []))}")

    print(f"\nScene created: {out_scene_dir}")
    print("Next: add the scene to the project via the UI or API, then Save Map to generate render_scene.xml.")


if __name__ == "__main__":
    main()
