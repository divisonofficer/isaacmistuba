"""User-painted walkability overlay layered on top of the auto-computed traversable grid.

The overlay shares its ``GridSpec`` with ``traversable_grid.npy`` so the two can be
combined cell-wise. Values:

- ``0`` — no user edit (use annotation traversable as-is)
- ``1`` — user marked **walkable** (force traversable, even if the auto grid said no)
- ``2`` — user marked **blocked** (force non-traversable, even if the auto grid said yes)

Persisted as a ``.npy`` next to ``traversable_grid.npy`` so it survives map rebuilds.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import numpy as np

from .traversability import GridSpec, world_to_cell


OVERLAY_VALUE_WALKABLE = 1
OVERLAY_VALUE_BLOCKED = 2
OVERLAY_VALUE_ERASE = 0


def make_empty_overlay(spec: GridSpec) -> np.ndarray:
    return np.zeros((spec.height, spec.width), dtype=np.uint8)


def _circle_mask(spec: GridSpec, world_x: float, world_y: float, radius_m: float) -> np.ndarray:
    """Boolean mask of cells whose centre falls inside the circle (world coords)."""
    if radius_m <= 0:
        return np.zeros((spec.height, spec.width), dtype=bool)
    ox, oy = float(spec.origin[0]), float(spec.origin[1])
    res = float(spec.resolution)
    # Cell index of the circle centre + a radius in cells.
    cx_f = (world_x - ox) / res
    cy_f = (world_y - oy) / res
    r_cells = radius_m / res
    # Bounding box of candidate cells.
    x_min = max(0, int(np.floor(cx_f - r_cells)))
    x_max = min(spec.width - 1, int(np.ceil(cx_f + r_cells)))
    y_min = max(0, int(np.floor(cy_f - r_cells)))
    y_max = min(spec.height - 1, int(np.ceil(cy_f + r_cells)))
    if x_max < x_min or y_max < y_min:
        return np.zeros((spec.height, spec.width), dtype=bool)
    ys = np.arange(y_min, y_max + 1)
    xs = np.arange(x_min, x_max + 1)
    yy, xx = np.meshgrid(ys, xs, indexing="ij")
    dx = xx - cx_f
    dy = yy - cy_f
    inside = (dx * dx + dy * dy) <= (r_cells * r_cells)
    mask = np.zeros((spec.height, spec.width), dtype=bool)
    mask[y_min : y_max + 1, x_min : x_max + 1] = inside
    return mask


def paint_circle(
    overlay: np.ndarray,
    spec: GridSpec,
    *,
    world_x: float,
    world_y: float,
    radius_m: float,
    value: int,
) -> np.ndarray:
    """Stamp a circular brush onto ``overlay`` in-place and return it.

    ``value`` must be one of OVERLAY_VALUE_*; passing ``0`` (erase) clears any
    previous walkable/blocked marks under the brush.
    """
    if overlay.shape != (spec.height, spec.width):
        raise ValueError(
            f"overlay shape {overlay.shape} does not match GridSpec ({spec.height}, {spec.width})"
        )
    mask = _circle_mask(spec, world_x, world_y, radius_m)
    if not mask.any():
        return overlay
    overlay[mask] = np.uint8(int(value))
    return overlay


def paint_strokes(
    overlay: np.ndarray,
    spec: GridSpec,
    *,
    points: Sequence[tuple[float, float]],
    radius_m: float,
    value: int,
) -> np.ndarray:
    """Apply a series of circular stamps (drag stroke), in order."""
    for x, y in points:
        paint_circle(overlay, spec, world_x=float(x), world_y=float(y), radius_m=radius_m, value=value)
    return overlay


def paint_rectangle(
    overlay: np.ndarray,
    spec: GridSpec,
    *,
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    value: int,
) -> np.ndarray:
    if overlay.shape != (spec.height, spec.width):
        raise ValueError("shape mismatch")
    x0, y0 = world_to_cell(spec, min(min_x, max_x), min(min_y, max_y))
    x1, y1 = world_to_cell(spec, max(min_x, max_x), max(min_y, max_y))
    x0 = max(0, x0); y0 = max(0, y0)
    x1 = min(spec.width - 1, x1); y1 = min(spec.height - 1, y1)
    if x1 < x0 or y1 < y0:
        return overlay
    overlay[y0 : y1 + 1, x0 : x1 + 1] = np.uint8(int(value))
    return overlay


def merge_overlay(annotation_traversable: np.ndarray, overlay: np.ndarray | None) -> np.ndarray:
    """Combine the auto-computed mask with user paint.

    ``effective = (annotation_traversable | overlay==1) & ~(overlay==2)``
    """
    base = np.asarray(annotation_traversable, dtype=bool)
    if overlay is None:
        return base
    if overlay.shape != base.shape:
        raise ValueError(f"overlay shape {overlay.shape} != grid shape {base.shape}")
    forced_walkable = overlay == OVERLAY_VALUE_WALKABLE
    forced_blocked = overlay == OVERLAY_VALUE_BLOCKED
    return (base | forced_walkable) & ~forced_blocked


def save_overlay(path: str | Path, overlay: np.ndarray) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    # uint8 to keep the file small (~200 KB for a 450×422 office_lobby grid).
    np.save(output, overlay.astype(np.uint8, copy=False))
    return output


def load_overlay(path: str | Path, *, expected_spec: GridSpec | None = None) -> np.ndarray | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        arr = np.load(p)
    except Exception:
        return None
    if expected_spec is not None and arr.shape != (expected_spec.height, expected_spec.width):
        # Shape mismatch (e.g. the underlying annotation grew) — drop the overlay.
        return None
    return arr.astype(np.uint8, copy=False)


def overlay_stats(overlay: np.ndarray) -> dict[str, Any]:
    return {
        "walkable_cells": int((overlay == OVERLAY_VALUE_WALKABLE).sum()),
        "blocked_cells": int((overlay == OVERLAY_VALUE_BLOCKED).sum()),
        "total_cells": int(overlay.size),
    }
