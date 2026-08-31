"""Conservative, review-first detection of oversized navigation blockers.

The authoring map contains both scene structure and movable furniture.  A very
large furniture footprint can erase an entire room or choke its only approach,
making a sparse place-graph look mysteriously disconnected.  This module finds
only *review candidates*; it never changes an authoring map on its own.
"""

from __future__ import annotations

from typing import Any, Iterable

from .object_footprint import (
    ROOM_SHELL_OBJECT_TYPES,
    WALL_OBJECT_TYPES,
    footprint_bbox,
    object_blocks_at_height,
    object_footprint,
)


# Door/window geometry is small in area but semantically indispensable.  It is
# explicitly excluded even if a bad import happens to report a large footprint.
_PROTECTED_TYPES = {
    *ROOM_SHELL_OBJECT_TYPES,
    *WALL_OBJECT_TYPES,
    "door",
    "glass_door",
    "window",
    "light",
    "camera",
}


def _footprint_area_and_extent(footprint: tuple) -> tuple[float, float, list[float]]:
    min_x, min_y, max_x, max_y = footprint_bbox(footprint)
    width = max(0.0, float(max_x) - float(min_x))
    depth = max(0.0, float(max_y) - float(min_y))
    if footprint[0] == "rrect":
        # The axis-aligned bbox of a rotated table can be much larger than the
        # real occupied area.  Rank by the real oriented rectangle but expose
        # the bbox for the editor to frame/highlight.
        area = max(0.0, 4.0 * float(footprint[3]) * float(footprint[4]))
    else:
        area = width * depth
    return area, max(width, depth), [float(min_x), float(min_y), float(max_x), float(max_y)]


def navigation_blocker_candidates(
    objects: Iterable[dict[str, Any]],
    *,
    robot_height_m: float = 1.2,
    min_footprint_area_m2: float = 2.0,
    min_extent_m: float = 2.0,
) -> list[dict[str, Any]]:
    """Return removable, unusually large low-obstacle candidates.

    A candidate must explicitly or implicitly block navigation, be below robot
    body height, and satisfy both an area and an extent floor.  Thus normal
    chairs, shelves, walls, floors, doors, and emitters do not appear.  The
    caller presents this list for explicit user selection before deleting any
    object.
    """
    min_area = max(0.0, float(min_footprint_area_m2))
    min_extent = max(0.0, float(min_extent_m))
    candidates: list[dict[str, Any]] = []
    for raw in objects:
        if not isinstance(raw, dict):
            continue
        object_id = str(raw.get("id") or "")
        if not object_id:
            continue
        object_type = str(raw.get("type") or "").strip().lower()
        navigation = raw.get("navigation") if isinstance(raw.get("navigation"), dict) else {}
        geometry = raw.get("geometry") if isinstance(raw.get("geometry"), dict) else {}
        if (
            object_type in _PROTECTED_TYPES
            or bool(raw.get("is_emitter"))
            or navigation.get("blocks_navigation") is False
            or not object_blocks_at_height(geometry, robot_height_m=robot_height_m)
        ):
            continue
        footprint = object_footprint(geometry)
        if footprint is None:
            continue
        area, extent, bounds = _footprint_area_and_extent(footprint)
        if area + 1e-9 < min_area or extent + 1e-9 < min_extent:
            continue
        size = geometry.get("size_m") if isinstance(geometry.get("size_m"), (list, tuple)) else []
        try:
            height = abs(float(size[1])) if len(size) >= 2 else 0.0
        except (TypeError, ValueError):
            height = 0.0
        reasons = ["large_blocking_footprint"]
        if height >= 6.0:
            reasons.append("unusually_tall_geometry")
        candidates.append({
            "object_id": object_id,
            "label": str(raw.get("label") or object_id),
            "object_type": object_type or "object",
            "footprint_area_m2": round(area, 3),
            "max_extent_m": round(extent, 3),
            "bounds": [round(value, 4) for value in bounds],
            "base_height_m": float(geometry.get("base_height_m") or 0.0),
            "geometry_height_m": round(height, 3),
            "reasons": reasons,
            # Largest blockers first; anomalous vertical geometry is a useful
            # tiebreaker for imported assets with bad transforms.
            "score": round(area + min(height, 20.0) * 0.05, 3),
        })
    candidates.sort(key=lambda item: (-float(item["score"]), str(item["object_id"])))
    return candidates
