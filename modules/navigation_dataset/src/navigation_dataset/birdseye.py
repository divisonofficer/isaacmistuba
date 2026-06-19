"""Top-down bird's-eye render of a scene: traversability grid + viewpoint graph
+ episode paths, as a single PNG summary. PIL/numpy are imported lazily so the
package has no hard dependency on them — missing deps just skip the render.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable


def node_cell_map(vgraph: dict, grid_spec: dict) -> dict[str, tuple[int, int]]:
    """Map node_id -> integer grid cell (col, row), deriving from world if absent."""
    origin = grid_spec.get("origin", [0.0, 0.0]) if grid_spec else [0.0, 0.0]
    res = (grid_spec.get("resolution", 1.0) if grid_spec else 1.0) or 1.0
    out: dict[str, tuple[int, int]] = {}
    for n in vgraph.get("nodes", []) or []:
        nid = n.get("node_id")
        if not nid:
            continue
        cell = (n.get("extras") or {}).get("cell")
        if cell is None:
            pos = n.get("position") or n.get("world") or [0.0, 0.0]
            cell = [round((pos[0] - origin[0]) / res), round((pos[1] - origin[1]) / res)]
        out[nid] = (int(cell[0]), int(cell[1]))
    return out


def render_birdseye(
    grid_npy: str | Path,
    grid_spec: dict,
    vgraph: dict,
    episodes: Iterable[dict] | None,
    dst_png: str | Path,
    *,
    scale: int = 4,
) -> Path | None:
    """Render a top-down grid map with the viewpoint graph + episode paths overlaid.

    ``episodes`` is an iterable of episode dicts (only ``path_nodes`` is used).
    Returns the written PNG path, or ``None`` if numpy/PIL or the grid is missing.
    """
    try:
        import numpy as np
        from PIL import Image, ImageDraw
    except Exception:
        return None
    grid_npy = Path(grid_npy)
    dst_png = Path(dst_png)
    try:
        grid = np.load(grid_npy)
    except Exception:
        return None

    h, w = grid.shape
    scale = max(1, int(scale))
    palette = {0: (45, 45, 48), 1: (232, 232, 235), 2: (196, 72, 72)}  # obstacle / traversable / hazard
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    for val, col in palette.items():
        rgb[grid == val] = col
    img = Image.fromarray(rgb, "RGB").transpose(Image.FLIP_TOP_BOTTOM)  # +y world points up
    img = img.resize((w * scale, h * scale), Image.NEAREST).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")

    def px(cell: tuple[int, int]) -> tuple[int, int]:
        cx, cy = cell
        return (cx * scale + scale // 2, (h - 1 - cy) * scale + scale // 2)

    cellmap = node_cell_map(vgraph, grid_spec)

    # Graph edges (connectivity).
    ew = max(1, scale // 2)
    for e in vgraph.get("edges", []) or []:
        s = cellmap.get(e.get("source"))
        t = cellmap.get(e.get("target"))
        if s and t:
            draw.line([px(s), px(t)], fill=(90, 140, 220, 150), width=ew)

    # Graph nodes.
    r = max(1, scale)
    for cell in cellmap.values():
        x, y = px(cell)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(40, 90, 200, 230))

    # Episode vertex navigation paths.
    ep_colors = [(255, 160, 0), (0, 200, 120), (220, 60, 200), (0, 180, 220), (255, 90, 90)]
    for i, ep in enumerate(episodes or []):
        nodes = (ep or {}).get("path_nodes") or []
        pts = [px(cellmap[n]) for n in nodes if n in cellmap]
        if len(pts) >= 2:
            draw.line(pts, fill=ep_colors[i % len(ep_colors)] + (255,), width=max(2, scale))
        if pts:
            sx, sy = pts[0]
            draw.ellipse([sx - 2 * r, sy - 2 * r, sx + 2 * r, sy + 2 * r], fill=(0, 220, 0, 255))
            gx, gy = pts[-1]
            draw.ellipse([gx - 2 * r, gy - 2 * r, gx + 2 * r, gy + 2 * r], fill=(230, 0, 0, 255))

    dst_png.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst_png, "PNG", optimize=True)
    return dst_png
