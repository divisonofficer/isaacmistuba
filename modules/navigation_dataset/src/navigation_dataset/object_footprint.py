"""Shared 2D object-footprint geometry for OpticalNav.

Pure-geometry helpers (no numpy / grid dependency) describing an authoring or
overlay object's footprint in the (x, authoring-y == world-z) plane. Used both
to flag grid vertices that overlap objects (``viewpoint_graph``) and to carve
object footprints out of the traversability grid (``traversability``).

The renderer applies ``rotate y angle=yaw_deg`` about world +Y (with world Z =
authoring y), so point objects are tested as *oriented* rectangles that respect
``yaw_deg`` exactly — a long desk rotated 90° is handled along its real axis
instead of a loose axis-aligned bounding box.
"""
from __future__ import annotations

import math
from typing import Any

JsonDict = dict[str, Any]

# Object types that make up the room boundary; never treated as obstacles here.
ROOM_SHELL_OBJECT_TYPES = {"floor", "ceiling", "__room_shell__"}
# Wall-like boundary objects.
WALL_OBJECT_TYPES = {"wall", "glass_wall", "mirror_wall"}


def object_footprint(geometry: JsonDict, *, margin: float = 0.0) -> tuple | None:
    """2D footprint descriptor of an object in the (x, authoring-y) plane.

    Descriptor forms:
      ``("aabb", min_x, min_y, max_x, max_y)``
      ``("rrect", cx, cy, half_w, half_d, cos, sin)``
    Returns ``None`` for unsupported geometry.
    """
    gtype = str(geometry.get("type") or "")
    if gtype == "line":
        start, end = geometry.get("start"), geometry.get("end")
        if not (isinstance(start, (list, tuple)) and isinstance(end, (list, tuple))):
            return None
        sx, sy = float(start[0]), float(start[1])
        ex, ey = float(end[0]), float(end[1])
        half = max(0.005, float(geometry.get("thickness_m") or 0.08) / 2.0) + margin
        return ("aabb", min(sx, ex) - half, min(sy, ey) - half, max(sx, ex) + half, max(sy, ey) + half)
    if gtype == "rectangle":
        bounds = geometry.get("bounds")
        if not (isinstance(bounds, (list, tuple)) and len(bounds) == 4):
            return None
        b = [float(v) for v in bounds]
        return ("aabb", min(b[0], b[2]) - margin, min(b[1], b[3]) - margin, max(b[0], b[2]) + margin, max(b[1], b[3]) + margin)
    if gtype == "box":
        bounds = geometry.get("bounds")
        if not (isinstance(bounds, (list, tuple)) and len(bounds) == 4):
            return None
        b = [float(v) for v in bounds]
        return ("aabb", min(b[0], b[2]) - margin, min(b[1], b[3]) - margin, max(b[0], b[2]) + margin, max(b[1], b[3]) + margin)
    if gtype == "circle":
        center = geometry.get("center")
        if not (isinstance(center, (list, tuple)) and len(center) >= 2):
            return None
        cx, cy = float(center[0]), float(center[1])
        r = float(geometry.get("radius") or 0.0) + margin
        return ("aabb", cx - r, cy - r, cx + r, cy + r)
    if gtype == "point":
        center = geometry.get("center")
        if not (isinstance(center, (list, tuple)) and len(center) >= 2):
            return None
        cx, cy = float(center[0]), float(center[1])
        size = geometry.get("size_m") or []
        w = float(size[0]) if len(size) >= 1 else 0.4
        d = float(size[2]) if len(size) >= 3 else (float(size[1]) if len(size) >= 2 else w)
        yaw = math.radians(float(geometry.get("yaw_deg") or 0.0))
        return ("rrect", cx, cy, w / 2.0 + margin, d / 2.0 + margin, math.cos(yaw), math.sin(yaw))
    return None


def footprint_bbox(fp: tuple) -> tuple[float, float, float, float]:
    """Axis-aligned bounding box (min_x, min_y, max_x, max_y) of a footprint."""
    if fp[0] == "aabb":
        return fp[1], fp[2], fp[3], fp[4]
    # rrect: bbox of the rotated rectangle.
    _, cx, cy, half_w, half_d, cos_a, sin_a = fp
    ex = abs(half_w * cos_a) + abs(half_d * sin_a)
    ey = abs(half_w * sin_a) + abs(half_d * cos_a)
    return cx - ex, cy - ey, cx + ex, cy + ey


def point_in_footprint(x: float, y: float, fp: tuple) -> bool:
    if fp[0] == "aabb":
        _, min_x, min_y, max_x, max_y = fp
        return min_x <= x <= max_x and min_y <= y <= max_y
    # rrect: rotate the point into the object's local frame (inverse yaw).
    _, cx, cy, half_w, half_d, cos_a, sin_a = fp
    dx, dy = x - cx, y - cy
    local_x = dx * cos_a - dy * sin_a
    local_y = dx * sin_a + dy * cos_a
    return abs(local_x) <= half_w and abs(local_y) <= half_d


def object_blocks_at_height(geometry: JsonDict, *, robot_height_m: float) -> bool:
    """True unless the object floats entirely above the robot.

    A ceiling light mounted at ``base_height_m=2.65`` does not obstruct a robot
    passing underneath, so objects whose bottom is at/above ``robot_height_m`` are
    not treated as obstacles. Low furniture (desks at base 0) still blocks.
    """
    base = float(geometry.get("base_height_m") or 0.0)
    return base < robot_height_m
