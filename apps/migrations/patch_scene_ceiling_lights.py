#!/usr/bin/env python3
"""Patch an existing scene to use room-level ceiling softboxes in authoring_map.json
(the source of truth), then optionally regenerate render_scene.xml through the
supported sync pipeline.

Why authoring_map and not render_scene.xml: hand-editing the compiled
render_scene.xml breaks the measured-pBRDF channel-split staging (verified). The
authoring map is the source; render_scene.xml is regenerated from it.

What it changes:
  * Adds a sparse set of `light_softbox_*` rectangle emitters per traversable room,
    based on the room floor AABB. These broad panels provide the real wall
    luminance floor.
  * Demotes existing ceiling fixtures from illumination sources to decorative
    meshes. Source-backed fixtures are kept with `is_emitter=false`; synthetic
    ceiling light proxies are removed.
  * Clears `.staged_mitsuba/` during recompile so stale cube-emitter scenes are
    not reused.

    # preview
    python apps/migrations/patch_scene_ceiling_lights.py indoor_seed2 --dry-run
    # patch authoring_map (backs up .bak), no recompile
    python apps/migrations/patch_scene_ceiling_lights.py indoor_seed2
    # patch + regenerate render_scene.xml via sync (validates measured_polarized loads)
    python apps/migrations/patch_scene_ceiling_lights.py indoor_seed2 --recompile
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (
    REPO_ROOT / "modules" / "robomituba_bridge" / "src",
    REPO_ROOT / "modules" / "mitsuba_converter" / "src",
    REPO_ROOT / "modules" / "navigation_dataset" / "src",
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SOFTBOX_TARGET_COVERAGE = 0.12
SOFTBOX_MIN_SIZE_M = 0.8
SOFTBOX_MAX_SIZE_M = 2.2
SOFTBOX_DEDUPE_DISTANCE_M = 1.15
SOFTBOX_FILL_RADIANCE = 3.0
SOFTBOX_PRIMARY_RADIANCE = 4.5


def _find_scene_dir(scene_id: str) -> Path:
    root = REPO_ROOT / "out" / "opticalnav"
    hits = sorted(root.glob(f"*/scenes/{scene_id}/authoring_map.json"))
    if not hits:
        raise SystemExit(f"[patch] no authoring_map.json for scene {scene_id!r} under {root}")
    return hits[0].parent


def _bounds_center(bounds: list[float]) -> tuple[float, float]:
    return ((float(bounds[0]) + float(bounds[2])) * 0.5, (float(bounds[1]) + float(bounds[3])) * 0.5)


def _point_in_bounds(point: list[float], bounds: list[float], *, margin: float = 0.05) -> bool:
    x = float(point[0])
    y = float(point[1])
    return (
        float(bounds[0]) - margin <= x <= float(bounds[2]) + margin
        and float(bounds[1]) - margin <= y <= float(bounds[3]) + margin
    )


def _traversable_regions(m: dict) -> list[dict]:
    regions = []
    for r in m.get("regions") or []:
        geom = r.get("geometry") or {}
        bounds = geom.get("bounds")
        if r.get("type") != "traversable" or not isinstance(bounds, list) or len(bounds) < 4:
            continue
        regions.append({"id": str(r.get("id") or f"room_{len(regions):02d}"), "bounds": [float(v) for v in bounds[:4]]})
    return regions


def _softbox_count_for_room(width: float, depth: float) -> int:
    area = max(0.0, float(width) * float(depth))
    if area < 35.0:
        return 1
    if area < 65.0:
        return 2
    if area < 105.0:
        return 3
    return 4


def _softbox_positions(min_x: float, min_y: float, width: float, depth: float, count: int) -> list[tuple[float, float]]:
    cx = min_x + width * 0.5
    cy = min_y + depth * 0.5
    if count <= 1:
        return [(cx, cy)]
    if count == 2:
        if width >= depth:
            return [(min_x + width / 3.0, cy), (min_x + width * 2.0 / 3.0, cy)]
        return [(cx, min_y + depth / 3.0), (cx, min_y + depth * 2.0 / 3.0)]
    if count == 3:
        if width >= depth * 1.45:
            return [(min_x + width * f, cy) for f in (0.25, 0.50, 0.75)]
        if depth >= width * 1.45:
            return [(cx, min_y + depth * f) for f in (0.25, 0.50, 0.75)]
        return [
            (min_x + width * 0.30, min_y + depth * 0.35),
            (min_x + width * 0.70, min_y + depth * 0.35),
            (min_x + width * 0.50, min_y + depth * 0.68),
        ]
    return [
        (min_x + width * 0.33, min_y + depth * 0.33),
        (min_x + width * 0.67, min_y + depth * 0.33),
        (min_x + width * 0.33, min_y + depth * 0.67),
        (min_x + width * 0.67, min_y + depth * 0.67),
    ]


def _softbox_specs(bounds: list[float], *, radiance: float) -> list[dict]:
    min_x, min_y, max_x, max_y = [float(v) for v in bounds[:4]]
    width = max(0.1, max_x - min_x)
    depth = max(0.1, max_y - min_y)
    count = _softbox_count_for_room(width, depth)
    target_area = width * depth * SOFTBOX_TARGET_COVERAGE / max(count, 1)
    target_side = math.sqrt(max(target_area, SOFTBOX_MIN_SIZE_M * SOFTBOX_MIN_SIZE_M))
    sx = min(SOFTBOX_MAX_SIZE_M, max(SOFTBOX_MIN_SIZE_M, target_side))
    sz = min(SOFTBOX_MAX_SIZE_M, max(SOFTBOX_MIN_SIZE_M, target_area / max(sx, 1e-6)))
    sx = min(sx, max(0.35, width * 0.80))
    sz = min(sz, max(0.35, depth * 0.80))
    specs = []
    for x, y in _softbox_positions(min_x, min_y, width, depth, count):
        specs.append({
            "center": [round(x, 4), round(y, 4)],
            "size_m": [round(sx, 4), 0.04, round(sz, 4)],
            "radiance": [round(float(radiance), 3)] * 3,
        })
    return specs


def _too_close_to_existing(center: list[float], softboxes: list[dict], *, min_distance: float) -> bool:
    cx = float(center[0])
    cy = float(center[1])
    for obj in softboxes:
        other = (obj.get("geometry") or {}).get("center") or [None, None]
        if len(other) < 2:
            continue
        dx = cx - float(other[0])
        dy = cy - float(other[1])
        if dx * dx + dy * dy < min_distance * min_distance:
            return True
    return False


def _is_ceiling_emitter(obj: dict, *, ceiling_min: float) -> bool:
    if not obj.get("is_emitter"):
        return False
    if str(obj.get("id") or "").startswith("light_softbox_"):
        return False
    geom = obj.get("geometry") or {}
    return float(geom.get("base_height_m") or 0.0) >= ceiling_min


def _is_synthetic_light_proxy(obj: dict) -> bool:
    obj_id = str(obj.get("id") or "")
    meta = obj.get("metadata") or {}
    return (
        obj_id.startswith("light_")
        or obj_id.startswith("light_synth_")
        or bool(meta.get("infinigen_light") and not obj.get("source_ref"))
    )


def _room_has_ceiling_light(objects: list[dict], bounds: list[float], *, ceiling_min: float) -> bool:
    for obj in objects:
        if not _is_ceiling_emitter(obj, ceiling_min=ceiling_min):
            continue
        geom = obj.get("geometry") or {}
        center = geom.get("center_xy") or geom.get("center")
        if isinstance(center, list) and len(center) >= 2 and _point_in_bounds(center, bounds):
            return True
    return False


def _patch_scene(
    m: dict,
    *,
    ceiling_min: float,
    ceiling_h: float,
    gap: float,
    fill_radiance: float,
    primary_radiance: float,
) -> dict:
    objects = list(m.get("objects") or [])
    regions = _traversable_regions(m)
    demoted = []
    removed = []
    kept = []
    for obj in objects:
        obj_id = str(obj.get("id") or "")
        if obj_id.startswith("light_softbox_"):
            removed.append(obj_id)
            continue
        if obj.get("is_emitter"):
            if _is_synthetic_light_proxy(obj):
                removed.append(obj_id)
                continue
            obj["is_emitter"] = False
            obj["emitter_intensity"] = 0.0
            obj["emitter_radiance"] = [0.0, 0.0, 0.0]
            obj.pop("emitter_shape", None)
            obj.setdefault("metadata", {})["lighting_policy"] = "decorative_non_emitting_fixture"
            demoted.append(obj_id)
        kept.append(obj)

    softboxes = []
    for ri, region in enumerate(regions):
        bounds = region["bounds"]
        had_fixture = _room_has_ceiling_light(objects, bounds, ceiling_min=ceiling_min)
        radiance = fill_radiance if had_fixture else primary_radiance
        for si, spec in enumerate(_softbox_specs(bounds, radiance=radiance)):
            center = spec["center"]
            if _too_close_to_existing(center, softboxes, min_distance=SOFTBOX_DEDUPE_DISTANCE_M):
                continue
            softboxes.append({
                "id": f"light_softbox_{region['id']}_{si:02d}",
                "type": "landmark",
                "label": f"Softbox {region['id']} {si:02d}",
                "placement": "point",
                "category": "ceiling_light",
                "source_ref": None,
                "geometry": {
                    "type": "point",
                    "center": center,
                    "yaw_deg": 0.0,
                    "pitch_deg": 0.0,
                    "roll_deg": 0.0,
                    "size_m": spec["size_m"],
                    "base_height_m": round(float(ceiling_h) - float(gap), 4),
                },
                "material": "infinigen_default",
                "navigation": {"blocks_navigation": False},
                "is_emitter": True,
                "emitter_shape": "ceiling_panel",
                "emitter_radiance": spec["radiance"],
                "emitter_intensity": 1.0,
                "metadata": {
                    "kind": "room_softbox",
                    "region_id": region["id"],
                    "region_bounds": bounds,
                    "normal_world": [0.0, -1.0, 0.0],
                    "ceiling_gap_m": float(gap),
                    "room_had_ceiling_fixture": had_fixture,
                    "lighting_policy": "primary_room_luminance_floor",
                },
            })

    m["objects"] = kept + softboxes
    m.setdefault("metadata", {})["lighting_policy"] = {
        "mode": "room_softbox_primary_fixture_decorative",
        "softbox_count": len(softboxes),
        "room_count": len(regions),
        "demoted_ceiling_fixture_count": len(demoted),
        "removed_synthetic_light_count": len(removed),
        "softbox_target_coverage": SOFTBOX_TARGET_COVERAGE,
        "softbox_max_per_region": 4,
        "softbox_dedupe_distance_m": SOFTBOX_DEDUPE_DISTANCE_M,
        "normal_world": [0.0, -1.0, 0.0],
    }
    return {
        "regions": regions,
        "softboxes": softboxes,
        "demoted": demoted,
        "removed": removed,
    }


def _recompile(scene_dir: Path) -> None:
    """Regenerate render_scene.xml from the patched authoring_map via the sync path."""
    from navigation_dataset.authoring_map import authoring_map_to_payload, load_authoring_map
    from navigation_dataset.scene_annotations import SceneAnnotation, read_scene_annotation
    from navigation_dataset.scene_sync import write_render_scene_sync
    from mitsuba_converter.render_daemon import _generate_opticalnav_render_scene_xml

    project_dir = scene_dir.parent.parent  # out/opticalnav/<version>
    map_path = scene_dir / "authoring_map.json"
    ann_path = scene_dir / "scene_annotation.json"
    render_scene_path = scene_dir / "render_scene.xml"
    eg_path = scene_dir / "editor_geometry.json"

    authoring_map = load_authoring_map(map_path)
    try:
        annotation = read_scene_annotation(ann_path)
    except (FileNotFoundError, ValueError, OSError):
        annotation = SceneAnnotation(scene_id=scene_dir.name)
    # clear staged cache so stale measured/envmap refs aren't reused
    staged = scene_dir / ".staged_mitsuba"
    if staged.exists():
        shutil.rmtree(staged, ignore_errors=True)
    result = write_render_scene_sync(scene_dir, authoring_map, annotation, project_dir=project_dir)
    payload = authoring_map_to_payload(authoring_map)
    eg_data = json.loads(eg_path.read_text()) if eg_path.exists() else None
    bak = render_scene_path.with_suffix(".xml.prepatch.bak")
    if render_scene_path.exists() and not bak.exists():
        shutil.copy2(render_scene_path, bak)
    n = _generate_opticalnav_render_scene_xml(
        payload, result.overlay, render_scene_path,
        editor_geometry=eg_data, repo_root=REPO_ROOT, mesh_resolver=None,
    )
    print(f"[patch] regenerated render_scene.xml ({n} shapes) — prepatch backup: {bak.name}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene_id")
    ap.add_argument("--ceiling-min", type=float, default=1.8, help="base_height ≥ this = ceiling fixture.")
    ap.add_argument("--ceiling-height", type=float, default=2.6)
    ap.add_argument("--gap", type=float, default=0.05)
    ap.add_argument("--fill-radiance", type=float, default=SOFTBOX_FILL_RADIANCE, help="Radiance for rooms that already had a ceiling fixture.")
    ap.add_argument("--primary-radiance", type=float, default=SOFTBOX_PRIMARY_RADIANCE, help="Radiance for traversable rooms without ceiling fixtures.")
    ap.add_argument("--recompile", action="store_true", help="also regenerate render_scene.xml via the sync pipeline.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    scene_dir = _find_scene_dir(args.scene_id)
    map_path = scene_dir / "authoring_map.json"
    m = json.loads(map_path.read_text())
    patch = _patch_scene(
        m,
        ceiling_min=args.ceiling_min,
        ceiling_h=args.ceiling_height,
        gap=args.gap,
        fill_radiance=args.fill_radiance,
        primary_radiance=args.primary_radiance,
    )
    regions = patch["regions"]
    softboxes = patch["softboxes"]
    print(
        f"[patch] scene={args.scene_id} traversable_rooms={len(regions)} "
        f"softboxes={len(softboxes)} demoted_fixtures={len(patch['demoted'])} "
        f"removed_light_proxies={len(patch['removed'])}"
    )
    for obj in softboxes[:5]:
        geom = obj["geometry"]
        print(
            f"  {obj['id']}: center={geom['center']} size={geom['size_m']} "
            f"base_h={geom['base_height_m']} radiance={obj['emitter_radiance'][0]}"
        )
    if len(softboxes) > 5:
        print(f"  ... +{len(softboxes) - 5} more softboxes")
    kept_room_count = len(m.get("metadata", {}).get("kept_rooms") or regions)
    print(
        f"[patch] acceptance preview: softbox_emitters={len(softboxes)} "
        f"kept_room_count={kept_room_count} normal_world=[0,-1,0] "
        f"base_height={round(args.ceiling_height - args.gap, 4)}"
    )

    if args.dry_run:
        print("[patch] dry-run: nothing written")
        return 0
    if not softboxes:
        print("[patch] no traversable room softboxes generated — nothing to do")
        return 1

    bak = map_path.with_suffix(".json.bak")
    if not bak.exists():
        shutil.copy2(map_path, bak)
        print(f"[patch] backup → {bak.name}")
    map_path.write_text(json.dumps(m, ensure_ascii=False, indent=2))
    print(f"[patch] wrote {map_path}")

    if args.recompile:
        _recompile(scene_dir)
    else:
        print("[patch] render_scene.xml NOT regenerated. Re-run with --recompile, or use the "
              "webui 'Sync Render Scene' / daemon POST /api/scenes/<id>/sync/render-scene.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
