#!/usr/bin/env python3
"""Remove the authoring objects that cut a scene's free space in two.

Infinigen's solver places furniture against its own clearance rules, which are
looser than the robot's. The result is a flat that looks fine but whose
traversable space is split into pieces a 0.28 m body can never move between --
a sofa across the only route into a room, a planter in a doorway. Those objects
have to go before a navigation graph is worth building.

Only *disconnecting* objects are pruned. An object that merely narrows a
corridor is kept on purpose: a tight route is a more interesting episode, not a
defect. The test is therefore connectivity, never footprint area -- a 0.40 m^2
cabinet in a doorway is fatal while a 3 m^2 bed against a wall is harmless.

Removals interact, so the search is greedy and iterative: prune one, recount,
repeat. Dry run by default; ``--apply`` rewrites authoring_map.json and records
what it took out.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "modules" / "navigation_dataset" / "src"))

import numpy as np
from scipy import ndimage

from navigation_dataset.scene_annotations import read_scene_annotation
from navigation_dataset.traversability import build_traversability_grid, inflate_traversable_grid

# v4's executable clearance: robot radius + policy margin + raster epsilon.
DEFAULT_CLEARANCE_M = 0.15 + 0.10 + 0.03
DEFAULT_RESOLUTION_M = 0.05
DEFAULT_ROBOT_HEIGHT_M = 1.2


def _component_sizes(annotation, objects, *, resolution: float, clearance: float,
                     robot_height: float) -> list[int]:
    grid = build_traversability_grid(
        annotation, resolution=resolution, objects=objects, robot_height_m=robot_height,
    )
    traversable = inflate_traversable_grid(grid.traversable, clearance, resolution)
    labels, count = ndimage.label(traversable)
    if count == 0:
        return []
    sizes = ndimage.sum_labels(traversable, labels, index=range(1, count + 1))
    return sorted((int(value) for value in sizes), reverse=True)


def _footprint_area(obj: dict) -> float:
    size = (obj.get("geometry") or {}).get("size_m") or [0.0, 0.0, 0.0]
    try:
        return float(size[0]) * float(size[1])
    except (TypeError, ValueError, IndexError):
        return 0.0


def prune(scene_dir: Path, *, resolution: float, clearance: float, robot_height: float,
          max_passes: int, apply: bool) -> dict:
    map_path = scene_dir / "authoring_map.json"
    authoring = json.loads(map_path.read_text(encoding="utf-8"))
    annotation = read_scene_annotation(scene_dir / "scene_annotation.json")
    objects = [dict(item) for item in authoring.get("objects") or []]

    baseline = _component_sizes(annotation, objects, resolution=resolution,
                                clearance=clearance, robot_height=robot_height)
    print(f"  free-space components before: {len(baseline)}  sizes={baseline[:6]}")

    removed: list[dict] = []
    for _pass in range(max_passes):
        current = _component_sizes(annotation, objects, resolution=resolution,
                                   clearance=clearance, robot_height=robot_height)
        if len(current) <= 1:
            break
        # Largest footprint first: when two objects cut the same doorway,
        # taking the bigger one out is the less surprising edit.
        candidates = sorted(
            (item for item in objects if (item.get("navigation") or {}).get("blocks_navigation")),
            key=_footprint_area, reverse=True,
        )
        cut = None
        for candidate in candidates:
            trial = [item for item in objects if item is not candidate]
            sizes = _component_sizes(annotation, trial, resolution=resolution,
                                     clearance=clearance, robot_height=robot_height)
            if len(sizes) < len(current):
                cut = (candidate, len(current) - len(sizes))
                break
        if cut is None:
            break
        candidate, merged = cut
        objects = [item for item in objects if item is not candidate]
        removed.append({
            "id": candidate.get("id"),
            "type": candidate.get("type"),
            "label": candidate.get("label"),
            "footprint_m2": round(_footprint_area(candidate), 3),
            "components_merged": merged,
        })
        print(f"    cut {str(candidate.get('type')):14} "
              f"{_footprint_area(candidate):5.2f} m^2  merged {merged} component(s)  "
              f"{str(candidate.get('id'))[:60]}")

    final = _component_sizes(annotation, objects, resolution=resolution,
                             clearance=clearance, robot_height=robot_height)
    print(f"  free-space components after:  {len(final)}  sizes={final[:6]}")
    print(f"  disconnecting objects found: {len(removed)}")

    report = {
        "scene_dir": str(scene_dir),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "clearance_m": clearance,
        "resolution_m": resolution,
        "components_before": len(baseline),
        "components_after": len(final),
        "removed": removed,
        "applied": bool(apply and removed),
    }
    if apply and removed:
        authoring["objects"] = objects
        map_path.write_text(json.dumps(authoring, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        (scene_dir / "navigation_blocker_prune.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  APPLIED: authoring_map.json rewritten, report at navigation_blocker_prune.json")
    elif removed:
        print("  dry run: pass --apply to remove them")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenes", nargs="+", help="Scene directory, or scene id under --project.")
    ap.add_argument("--project", default="out/opticalnav/opticalnav-v0.2",
                    help="Project root used to resolve bare scene ids.")
    ap.add_argument("--apply", action="store_true", help="Rewrite authoring_map.json.")
    ap.add_argument("--clearance-m", type=float, default=DEFAULT_CLEARANCE_M)
    ap.add_argument("--resolution-m", type=float, default=DEFAULT_RESOLUTION_M)
    ap.add_argument("--robot-height-m", type=float, default=DEFAULT_ROBOT_HEIGHT_M)
    ap.add_argument("--max-passes", type=int, default=25,
                    help="Upper bound on greedy removals per scene.")
    args = ap.parse_args()

    for name in args.scenes:
        scene_dir = Path(name)
        if not scene_dir.is_dir():
            scene_dir = REPO / args.project / "scenes" / name
        if not (scene_dir / "authoring_map.json").is_file():
            print(f"{name}: no authoring_map.json, skipped")
            continue
        print(f"{scene_dir.name}")
        prune(scene_dir, resolution=args.resolution_m, clearance=args.clearance_m,
              robot_height=args.robot_height_m, max_passes=args.max_passes, apply=args.apply)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
