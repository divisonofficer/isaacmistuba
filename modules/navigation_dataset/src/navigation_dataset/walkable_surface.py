"""Mesh-derived walkable surface for OpticalNav viewpoint-graph building.

Background
----------
The Infinigen import (``apps/import_infinigen_scene.py``) collapses scene geometry
into the annotation: floors become a single scene-bbox ``box``, walls become a
radius-0.2 circle at the room centre, furniture a radius-0.15 circle. The resulting
traversable grid is therefore ~the whole bounding box with no real walls, so the
auto graph sprays nodes outside curved/diagonal-walled rooms and runs edges through
where walls should be (users then delete 26-38% of nodes by hand).

The real per-room ``*.floor.obj`` / ``*.wall.obj`` meshes still exist under
``out/infinigen_imports/<root>/meshes/`` — the import just discarded their shape.
This module rebuilds an *accurate* 2D walkable + clearance grid directly from those
meshes, returning a :class:`~navigation_dataset.traversability.TraversabilityGrid`
so the existing ``sample_viewpoint_nodes`` / ``build_viewpoint_edges`` consume it
unchanged.

Coordinate frame
----------------
Meshes are exported Blender Y-up, mesh-local-centred. The annotation/graph
("authoring") frame is xy_yaw. The validated mapping (see the unit test in
``tests/test_walkable_surface.py``) for a vertex ``(xl, yl_up, zl)`` of a unit with
world AABB ``[wmin, wmax]`` (Blender Z-up world) and ``origin_offset = [dx, dy, dz]``::

    wc   = (wmin + wmax) / 2                 # world AABB centre
    lc   = (Vmin + Vmax) / 2                 # local AABB centre
    Xw   = (xl - lc.x) + wc.x                #   local X      -> world X
    Yw   = -(zl - lc.z) + wc.y               #   local Z (neg)-> world Y
    auth_x = Xw + dx
    auth_y = -Yw + dy

Structures (floor/wall/ceiling) have zero yaw so this is exact for them. Furniture
may carry arbitrary yaw, so furniture footprints are carved from the overlay
rotated-rect descriptors (already authoring-frame) rather than their meshes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .object_footprint import (
    ROOM_SHELL_OBJECT_TYPES,
    WALL_OBJECT_TYPES,
    object_blocks_at_height,
)
from .traversability import (
    GridSpec,
    TraversabilityGrid,
    cell_to_world,
    world_to_cell,
)
from .traversability import _mask_object_footprint  # rotated-footprint rasteriser

WALKABLE_SURFACE_VERSION = 1

# scene_manifest unit classification
_FLOOR_SUBTYPES = {"floor"}
_WALL_SUBTYPES = {"wall", "exterior"}
# Overlay object types that name a real door opening (portals).
_DOOR_OVERLAY_TYPES = {"door", "glass_door"}
# Floor coverings the robot drives over — never carve them (cat 4). Matched on the
# factory/id name because Infinigen marks them ``blocks_navigation`` and their height
# (a thick rug can be ~0.2 m) exceeds the low-profile threshold. "mat" is intentionally
# omitted to avoid matching "mattress".
_FLOOR_COVERING_NAME_PARTS = ("rug", "carpet", "runner", "doormat", "floormat")


def _is_floor_covering(obj: dict) -> bool:
    name = (str(obj.get("id") or "") + " " + str(obj.get("label") or "")).lower()
    return any(part in name for part in _FLOOR_COVERING_NAME_PARTS)


@dataclass
class PortalSpec:
    """A door opening that bridges two walkable regions."""

    door_id: str
    door_type: str
    center: tuple[float, float]
    axis: tuple[float, float]
    side_a: tuple[float, float]
    side_b: tuple[float, float]
    region_a: int | None = None
    region_b: int | None = None
    resolved: bool = True


@dataclass
class WalkableSurface:
    grid: TraversabilityGrid          # full walkable (largest island), un-eroded
    clearance_m: np.ndarray           # (H,W) float32 — obstacle distance in metres
    floor_mask: np.ndarray            # (H,W) bool — union of floor footprints (for QA)
    portals: list[PortalSpec] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Phase 0 — primitives
# --------------------------------------------------------------------------- #
def _project_to_authoring_xy(
    verts: np.ndarray,
    world_bbox_min,
    world_bbox_max,
    origin_offset,
) -> np.ndarray:
    """Map (V,3) Blender Y-up local-centred vertices to authoring (V,2) xy."""
    V = np.asarray(verts, dtype=np.float64)
    if V.ndim != 2 or V.shape[1] != 3 or len(V) == 0:
        return np.zeros((0, 2), dtype=np.float64)
    dx, dy, _dz = (float(v) for v in origin_offset)
    lc = (V.min(axis=0) + V.max(axis=0)) / 2.0
    wbmin = np.asarray(world_bbox_min, dtype=np.float64)
    wbmax = np.asarray(world_bbox_max, dtype=np.float64)
    wc = (wbmin + wbmax) / 2.0
    world_x = (V[:, 0] - lc[0]) + wc[0]
    world_y = -(V[:, 2] - lc[2]) + wc[1]
    auth_x = world_x + dx
    auth_y = -world_y + dy
    return np.column_stack([auth_x, auth_y])


def _rasterize_faces(spec: GridSpec, verts_xy: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Fill every triangle of ``faces`` (indices into authoring-xy ``verts_xy``).

    Triangle fill (skimage.draw.polygon) handles concave / curved / diagonal room
    outlines natively — this is why the pipeline needs no polygon-simplification
    (shapely). Returns a (H,W) bool mask.
    """
    from skimage.draw import polygon as sk_polygon

    mask = np.zeros((spec.height, spec.width), dtype=bool)
    if len(verts_xy) == 0 or len(faces) == 0:
        return mask
    # authoring xy -> fractional cell (col=x, row=y)
    col = (verts_xy[:, 0] - spec.origin[0]) / spec.resolution
    row = (verts_xy[:, 1] - spec.origin[1]) / spec.resolution
    for tri in faces:
        rr, cc = sk_polygon(row[tri], col[tri], shape=(spec.height, spec.width))
        mask[rr, cc] = True
    return mask


def _largest_island(mask: np.ndarray) -> np.ndarray:
    """Keep only the largest 4-connected True component."""
    from scipy import ndimage

    if not mask.any():
        return mask.copy()
    labels, n = ndimage.label(mask)
    if n <= 1:
        return mask.copy()
    counts = np.bincount(labels.ravel())
    counts[0] = 0  # background
    keep = int(counts.argmax())
    return labels == keep


# --------------------------------------------------------------------------- #
# Mesh loading / classification
# --------------------------------------------------------------------------- #
def _load_unit_faces(import_root: Path, unit: dict, origin_offset) -> tuple[np.ndarray, np.ndarray]:
    """Load a manifest unit's mesh and return (authoring_xy (V,2), faces (F,3))."""
    import trimesh

    rel = unit.get("mesh_obj")
    if not rel:
        return np.zeros((0, 2)), np.zeros((0, 3), dtype=int)
    path = import_root / rel
    if not path.is_file():
        return np.zeros((0, 2)), np.zeros((0, 3), dtype=int)
    try:
        mesh = trimesh.load(str(path), process=False, force="mesh")
    except Exception:
        return np.zeros((0, 2)), np.zeros((0, 3), dtype=int)
    verts = np.asarray(getattr(mesh, "vertices", np.zeros((0, 3))), dtype=np.float64)
    faces = np.asarray(getattr(mesh, "faces", np.zeros((0, 3))), dtype=np.int64)
    if len(verts) == 0 or len(faces) == 0:
        return np.zeros((0, 2)), np.zeros((0, 3), dtype=int)
    xy = _project_to_authoring_xy(
        verts, unit.get("world_bbox_min"), unit.get("world_bbox_max"), origin_offset
    )
    return xy, faces


def _structure_units(manifest: dict) -> tuple[list[dict], list[dict]]:
    floors, walls = [], []
    for u in manifest.get("units", []):
        if str(u.get("kind")) != "structure":
            continue
        sub = str(u.get("subtype") or "")
        if sub in _FLOOR_SUBTYPES:
            floors.append(u)
        elif sub in _WALL_SUBTYPES:
            walls.append(u)
    return floors, walls


# --------------------------------------------------------------------------- #
# Phase 2 — portals
# --------------------------------------------------------------------------- #
def _door_overlay_objects(overlay_objects) -> list[dict]:
    out = []
    for o in overlay_objects or []:
        if str(o.get("type") or "") in _DOOR_OVERLAY_TYPES:
            out.append(o)
    return out


def _cell_walkable(walkable: np.ndarray, spec: GridSpec, x: float, y: float) -> bool:
    cx, cy = world_to_cell(spec, x, y)
    return 0 <= cx < spec.width and 0 <= cy < spec.height and bool(walkable[cy, cx])


def _detect_portals(
    door_objects: list[dict],
    walkable: np.ndarray,
    spec: GridSpec,
    *,
    robot_radius_m: float,
) -> list[PortalSpec]:
    """For each door, find a walkable point on each side of the opening.

    ``yaw_deg`` in the overlay is unreliable (often 0), so the crossing axis is
    inferred from the footprint's short side and then *validated by probing the
    walkable mask*: both sides of the opening must be walkable.
    """
    from scipy import ndimage

    labels, _n = ndimage.label(walkable)

    def _region_at(x: float, y: float) -> int | None:
        cx, cy = world_to_cell(spec, x, y)
        if 0 <= cx < spec.width and 0 <= cy < spec.height and labels[cy, cx] > 0:
            return int(labels[cy, cx])
        return None

    portals: list[PortalSpec] = []
    for obj in door_objects:
        geom = obj.get("geometry") or {}
        center = geom.get("center")
        if not (isinstance(center, (list, tuple)) and len(center) >= 2):
            continue
        cx, cy = float(center[0]), float(center[1])
        size = geom.get("size_m") or []
        w = float(size[0]) if len(size) >= 1 else 0.9
        d = float(size[2]) if len(size) >= 3 else w
        # Crossing axis = perpendicular to the wider door-plane side.
        short_half = max(0.05, min(w, d) / 2.0)
        probe = short_half + robot_radius_m + 0.15
        plane_along_x = w >= d                 # door plane runs along x -> cross along y
        axes = [(0.0, 1.0), (1.0, 0.0)] if plane_along_x else [(1.0, 0.0), (0.0, 1.0)]
        # Add diagonal fallbacks for odd orientations.
        diag = math.sqrt(0.5)
        axes += [(diag, diag), (diag, -diag)]

        chosen: PortalSpec | None = None
        for ax, ay in axes:
            ax_a = (cx + ax * probe, cy + ay * probe)
            ax_b = (cx - ax * probe, cy - ay * probe)
            if _cell_walkable(walkable, spec, *ax_a) and _cell_walkable(walkable, spec, *ax_b):
                ra, rb = _region_at(*ax_a), _region_at(*ax_b)
                chosen = PortalSpec(
                    door_id=str(obj.get("object_id") or obj.get("id") or f"door_{len(portals)}"),
                    door_type=str(obj.get("type") or "door"),
                    center=(cx, cy),
                    axis=(ax, ay),
                    side_a=ax_a,
                    side_b=ax_b,
                    region_a=ra,
                    region_b=rb,
                    resolved=True,
                )
                # Prefer an axis that bridges two *distinct* regions.
                if ra is not None and rb is not None and ra != rb:
                    break
        if chosen is None:
            chosen = PortalSpec(
                door_id=str(obj.get("object_id") or obj.get("id") or f"door_{len(portals)}"),
                door_type=str(obj.get("type") or "door"),
                center=(cx, cy),
                axis=(0.0, 0.0),
                side_a=(cx, cy),
                side_b=(cx, cy),
                region_a=None,
                region_b=None,
                resolved=False,
            )
        portals.append(chosen)
    return portals


def _stamp_disc(mask: np.ndarray, spec: GridSpec, x: float, y: float, radius_m: float) -> None:
    cx, cy = world_to_cell(spec, x, y)
    r = max(1, int(round(radius_m / spec.resolution)))
    y0, y1 = max(0, cy - r), min(spec.height - 1, cy + r)
    x0, x1 = max(0, cx - r), min(spec.width - 1, cx + r)
    for yy in range(y0, y1 + 1):
        for xx in range(x0, x1 + 1):
            if (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r:
                mask[yy, xx] = True


# --------------------------------------------------------------------------- #
# Phase 1 — assemble the walkable surface
# --------------------------------------------------------------------------- #
def build_walkable_surface(
    scene_id: str,
    *,
    import_root: Path,
    origin_offset,
    overlay_objects: list[dict] | None = None,
    resolution: float = 0.05,
    margin: float = 0.3,
    robot_radius_m: float = 0.25,
    robot_height_m: float = 1.2,
    low_profile_max_height_m: float = 0.03,
    wall_inflate_m: float = 0.0,
    portal_stamp_radius_m: float = 0.18,
) -> WalkableSurface:
    """Build an accurate 2D walkable + clearance grid from per-room meshes."""
    from scipy import ndimage

    import_root = Path(import_root)
    manifest_path = import_root / "scene_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    floors, walls = _structure_units(manifest)
    if not floors:
        raise ValueError(f"{scene_id}: scene_manifest has no floor structures to build a walkable surface.")

    # --- grid bounds from floor footprints --------------------------------- #
    floor_faces: list[tuple[np.ndarray, np.ndarray]] = []
    minx = miny = math.inf
    maxx = maxy = -math.inf
    for u in floors:
        xy, faces = _load_unit_faces(import_root, u, origin_offset)
        if len(xy) == 0:
            continue
        floor_faces.append((xy, faces))
        minx, miny = min(minx, xy[:, 0].min()), min(miny, xy[:, 1].min())
        maxx, maxy = max(maxx, xy[:, 0].max()), max(maxy, xy[:, 1].max())
    if not floor_faces:
        raise ValueError(f"{scene_id}: no floor meshes could be loaded from {import_root}.")
    minx -= margin
    miny -= margin
    maxx += margin
    maxy += margin
    width = max(1, int(math.ceil((maxx - minx) / resolution)))
    height = max(1, int(math.ceil((maxy - miny) / resolution)))
    spec = GridSpec(origin=[float(minx), float(miny)], resolution=float(resolution),
                    width=width, height=height, scene_id=scene_id)

    # --- floors -> walkable ------------------------------------------------ #
    floor_mask = np.zeros((height, width), dtype=bool)
    for xy, faces in floor_faces:
        floor_mask |= _rasterize_faces(spec, xy, faces)

    # --- walls -> carve ---------------------------------------------------- #
    wall_mask = np.zeros((height, width), dtype=bool)
    for u in walls:
        xy, faces = _load_unit_faces(import_root, u, origin_offset)
        if len(xy):
            wall_mask |= _rasterize_faces(spec, xy, faces)
    if wall_inflate_m > 0 and wall_mask.any():
        it = max(1, int(round(wall_inflate_m / resolution)))
        wall_mask = ndimage.binary_dilation(wall_mask, iterations=it)

    walkable = floor_mask & ~wall_mask

    # --- furniture -> carve from overlay rotated footprints ---------------- #
    n_furn = n_lowprofile = 0
    for obj in overlay_objects or []:
        otype = str(obj.get("type") or "")
        if otype in ROOM_SHELL_OBJECT_TYPES or otype in WALL_OBJECT_TYPES:
            continue  # floors/ceilings + (whole-room) walls handled via meshes
        if otype in _DOOR_OVERLAY_TYPES:
            continue  # doors are passages, not obstacles — handled as portals below
        if _is_floor_covering(obj):
            n_lowprofile += 1            # rug/carpet — robot drives over it (cat 4)
            continue
        nav = obj.get("navigation") or {}
        if nav.get("blocks_navigation") is False:
            continue
        geom = obj.get("geometry") or {}
        if not object_blocks_at_height(geom, robot_height_m=robot_height_m):
            continue
        size = geom.get("size_m") or []
        if len(size) >= 2 and float(size[1]) < low_profile_max_height_m:
            n_lowprofile += 1            # thin threshold strip — drive over (cat 4)
            continue
        fp_mask = _mask_object_footprint(spec, geom)
        if fp_mask.any():
            walkable &= ~fp_mask
            n_furn += 1

    # --- portals ----------------------------------------------------------- #
    door_objs = _door_overlay_objects(overlay_objects)
    portals = _detect_portals(door_objs, walkable, spec, robot_radius_m=robot_radius_m)
    # Stamp a small walkable disc at every resolved portal so adjacent rooms join
    # through the doorway (otherwise rooms split into separate islands).
    for p in portals:
        if p.resolved:
            _stamp_disc(walkable, spec, p.center[0], p.center[1], portal_stamp_radius_m)

    # --- largest island ---------------------------------------------------- #
    island = _largest_island(walkable)

    # --- clearance (EDT) --------------------------------------------------- #
    clearance_m = ndimage.distance_transform_edt(island).astype(np.float32) * float(resolution)

    grid = TraversabilityGrid(
        spec=spec,
        traversable=island,
        hazard=np.zeros((height, width), dtype=bool),
    )
    stats = {
        "walkable_surface_version": WALKABLE_SURFACE_VERSION,
        "floor_units": len(floor_faces),
        "wall_units": len(walls),
        "furniture_carved": n_furn,
        "low_profile_skipped": n_lowprofile,
        "floor_cells": int(floor_mask.sum()),
        "walkable_cells": int(walkable.sum()),
        "island_cells": int(island.sum()),
        "portals": len(portals),
        "portals_unresolved": sum(1 for p in portals if not p.resolved),
        "grid": {"width": width, "height": height, "resolution": resolution,
                 "origin": [float(minx), float(miny)]},
    }
    return WalkableSurface(grid=grid, clearance_m=clearance_m, floor_mask=floor_mask,
                           portals=portals, stats=stats)
