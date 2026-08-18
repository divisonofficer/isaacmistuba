#!/usr/bin/env python3
"""Seed-driven procedural floor-plan generator for Infinigen indoor scenes.

Emits the same floor-plan dict that ``infinigen_gen.py``'s hand-authored builders
produce (rooms / doors / opens / interiors / windows, each ``{"shape": "<shapely
expr string>"}``), but *generated* from a seed so every plan differs while staying
VALID for Infinigen's solver.

Four archetypes:
  - "apartment": living-room-centered, one central corridor band, open LDK
    (living/kitchen/dining joined by ``opens``), bedrooms + bathroom off the
    corridor. Hub-and-spoke nav graph.
  - "office": a corridor network (full-width spine + vertical branches) with many
    small rooms budding off the corridors; rooms at spine x branch junctions touch
    two corridors -> varied entry counts.
  - "office_modern_hybrid_v1": a compact, contemporary office suite with an
    open-plan work area, a support bar and a small number of meeting/focus rooms.
  - "single_room": exactly one semantic room with a south entrance and a north
    exterior window; outdoor context is intentionally deferred to a Mitsuba
    environment map.

WHY BSP: a recursive rectangular partition guarantees Infinigen's #1 hard
constraint by construction -- rooms tile the footprint with no gaps/overlaps, so
``exterior = shapely.union_all(rooms)`` (predefined.py:158) is a single clean
polygon. Corridors are carved FIRST as real rectangles, then each room band is cut
perpendicular to its corridor so every room has a full-frontage (>= MIN_DIM) edge
on a corridor -- comfortably above Infinigen's strict ``> 1.4 m`` door threshold
(solidifier.py:450).

This module is PURE PYTHON (stdlib only): shapely is only available in the
infinigen conda env, so the core operates on float tuples and emits strings. The
optional ``validate_plan_shapely`` imports shapely lazily.
"""

from __future__ import annotations

import random
import re
import hashlib
import json
from dataclasses import dataclass

# --- constants (meters) ----------------------------------------------------

UNIT = 0.5          # grid quantization (Infinigen uses 0.5 m unit_cast)
MIN_DIM = 2.0       # every cell >= 2 m per side -> full-side shared edges >= 2 m
MARGIN = 1.4        # Infinigen segment_margin: door needs shared edge STRICTLY > this
DOOR_MIN = 1.6      # only emit a door on edges >= this (safety above MARGIN)
DOOR_W = 1.0        # door opening width
OPEN_W = 1.8        # LDK / corridor-junction open width
WIN_MIN = 1.2       # min exterior edge to place a window
WIN_MAX = 3.0       # max window width
CW = 1.5            # corridor width (> MARGIN)

MODERN_OFFICE_PROFILE = "modern_hybrid_v1"
MODERN_OFFICE_ARCHETYPE = "office_modern_hybrid_v1"
# These are deliberately tenant-suite rather than whole-tower floor plates.  They
# preserve the visual grammar of a contemporary office while keeping Infinigen
# solve/import and OpticalNav graph costs bounded.
MODERN_OFFICE_DIMENSIONS = (
    (15.0, 12.0),  # 180 m²
    (16.0, 13.0),  # 208 m²
    (18.0, 13.0),  # 234 m²
    (18.0, 14.0),  # 252 m²
    (20.0, 14.0),  # 280 m²
    (18.0, 16.0),  # 288 m²
)
MODERN_OFFICE_TOPOLOGIES = ("facade_bar", "side_core", "split_neighborhood")
MODERN_OFFICE_STYLES = ("modern_basic_v1", "modern_glass_v1")
MODERN_GLASS_PARTITION_COUNT = 3

SINGLE_ROOM_TYPES = (
    "living-room",
    "bedroom",
    "kitchen",
    "bathroom",
    "dining-room",
    "closet",
    "hallway",
    "garage",
    "balcony",
    "utility",
    "staircase-room",
    "warehouse",
    "office",
    "meeting-room",
    "open-office",
    "break-room",
    "restroom",
    "factory-office",
)

# Room-specific dimensions keep furniture placement plausible while retaining
# enough variation for inverse-rendering batches.
SINGLE_ROOM_PROFILES = {
    "living-room": {"sizes": [(5.5, 4.5), (6.0, 5.0), (6.5, 5.0)], "window_width": 3.5, "panoramic": True},
    "bedroom": {"sizes": [(4.0, 3.5), (4.5, 4.0), (5.0, 4.0)], "window_width": 2.2, "panoramic": False},
    "kitchen": {"sizes": [(4.0, 3.5), (4.5, 4.0), (5.0, 4.0)], "window_width": 2.4, "panoramic": False},
    "bathroom": {"sizes": [(2.8, 2.8), (3.0, 3.0), (3.5, 3.0)], "window_width": 1.4, "panoramic": False},
    "dining-room": {"sizes": [(4.5, 4.0), (5.0, 4.5), (5.5, 4.5)], "window_width": 2.8, "panoramic": False},
    "closet": {"sizes": [(2.5, 2.0), (3.0, 2.5), (3.5, 2.5)], "window_width": 1.2, "panoramic": False},
    "hallway": {"sizes": [(5.0, 2.0), (6.0, 2.5), (7.0, 2.5)], "window_width": 1.5, "panoramic": False},
    "garage": {"sizes": [(5.5, 5.0), (6.0, 5.5), (7.0, 6.0)], "window_width": 2.5, "panoramic": False},
    "balcony": {"sizes": [(3.5, 2.5), (4.5, 3.0), (5.5, 3.0)], "window_width": 2.5, "panoramic": True},
    "utility": {"sizes": [(3.0, 2.5), (3.5, 3.0), (4.0, 3.0)], "window_width": 1.5, "panoramic": False},
    "staircase-room": {"sizes": [(3.5, 3.5), (4.0, 4.0), (4.5, 4.0)], "window_width": 1.8, "panoramic": False},
    "warehouse": {"sizes": [(8.0, 6.0), (10.0, 7.0), (12.0, 8.0)], "window_width": 4.0, "panoramic": True},
    "office": {"sizes": [(3.5, 3.0), (4.0, 3.5), (4.5, 4.0)], "window_width": 2.2, "panoramic": False},
    "meeting-room": {"sizes": [(5.0, 4.0), (6.0, 4.5), (7.0, 5.0)], "window_width": 3.0, "panoramic": False},
    "open-office": {"sizes": [(7.0, 5.5), (8.0, 6.0), (10.0, 7.0)], "window_width": 4.0, "panoramic": True},
    "break-room": {"sizes": [(4.0, 3.5), (4.5, 4.0), (5.0, 4.0)], "window_width": 2.2, "panoramic": False},
    "restroom": {"sizes": [(2.8, 2.8), (3.0, 3.0), (3.5, 3.0)], "window_width": 1.4, "panoramic": False},
    "factory-office": {"sizes": [(4.0, 3.5), (4.5, 4.0), (5.5, 4.5)], "window_width": 2.4, "panoramic": False},
}


def q(v: float, unit: float = UNIT) -> float:
    """Quantize to the grid so edges align exactly (no float slivers)."""
    return round(round(v / unit) * unit, 3)


def _g(v: float) -> str:
    return f"{v:g}"


# --- geometry helpers (axis-aligned rects: (x0, y0, x1, y1)) ----------------

Rect = tuple  # (x0, y0, x1, y1)


def area(r: Rect) -> float:
    return (r[2] - r[0]) * (r[3] - r[1])


def overlap_area(a: Rect, b: Rect) -> float:
    ox = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    oy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return ox * oy


def shared_edge(a: Rect, b: Rect):
    """Return (orient, const, lo, hi, length) for the touching edge of two boxes,
    or None. orient 'v' => vertical edge at x=const, span on y in [lo,hi];
    'h' => horizontal edge at y=const, span on x in [lo,hi]."""
    eps = 1e-6
    for ra, rb in ((a, b), (b, a)):
        if abs(ra[2] - rb[0]) < eps:  # ra right meets rb left at x = ra[2]
            lo, hi = max(ra[1], rb[1]), min(ra[3], rb[3])
            if hi - lo > eps:
                return ("v", ra[2], lo, hi, hi - lo)
    for ra, rb in ((a, b), (b, a)):
        if abs(ra[3] - rb[1]) < eps:  # ra top meets rb bottom at y = ra[3]
            lo, hi = max(ra[0], rb[0]), min(ra[2], rb[2])
            if hi - lo > eps:
                return ("h", ra[3], lo, hi, hi - lo)
    return None


def _mirror_y(r: Rect, extent: float) -> Rect:
    """Flip a rect across the horizontal midline of a `extent`-tall footprint,
    keeping y0 < y1. Used to vary which band (LDK vs bedrooms) sits at the
    building's south vs north side."""
    x0, y0, x1, y1 = r
    return (x0, q(extent - y1), x1, q(extent - y0))


def _transpose_rect(r: Rect) -> Rect:
    """Swap x/y axes of a rect. Applying this to every cell in a valid tiling
    yields another valid tiling (rotated 90deg) -- used to vary whether the
    corridor runs along the building's long or short axis."""
    x0, y0, x1, y1 = r
    return (y0, x0, y1, x1)


def _box_str(r: Rect) -> str:
    return f"shapely.box({_g(r[0])},{_g(r[1])},{_g(r[2])},{_g(r[3])})"


def _line_str(p0, p1) -> str:
    return f"shapely.LineString([({_g(p0[0])},{_g(p0[1])}),({_g(p1[0])},{_g(p1[1])})])"


def _centered_line(orient, const, lo, hi, width):
    m = (lo + hi) / 2.0
    half = min(width, hi - lo) / 2.0
    if orient == "v":
        return ((const, q(m - half)), (const, q(m + half)))
    return ((q(m - half), const), (q(m + half), const))


# --- partition -------------------------------------------------------------


@dataclass
class Cell:
    rect: Rect
    type: str
    ldk: bool = False
    is_corridor: bool = False
    name: str = ""


def partition_widths(span: float, rng: random.Random, n: int | None = None):
    """Split `span` into widths each >= MIN_DIM, summing EXACTLY to span, all on
    the 0.5 grid. `n` caps the count (clamped to what fits)."""
    cap = int(span // MIN_DIM)
    if cap < 1:
        return [span]
    n = cap if n is None else max(1, min(n, cap))
    chunks = int(round((span - n * MIN_DIM) / UNIT))
    widths = [MIN_DIM] * n
    for _ in range(max(0, chunks)):
        widths[rng.randrange(n)] += UNIT
    return widths


def cut_band(rect: Rect, axis: str, n: int | None, rng: random.Random):
    """Cut a rect into columns ('x') or rows ('y'). Exact tiling, each >= MIN_DIM."""
    x0, y0, x1, y1 = rect
    span = (x1 - x0) if axis == "x" else (y1 - y0)
    widths = partition_widths(span, rng, n)
    out, cur = [], (x0 if axis == "x" else y0)
    for w in widths:
        if axis == "x":
            out.append((q(cur), y0, q(cur + w), y1))
        else:
            out.append((x0, q(cur), x1, q(cur + w)))
        cur += w
    return out


# --- archetype builders ----------------------------------------------------


def build_apartment(rng: random.Random, target_rooms: int):
    """Corridor-band apartment. Two independent binary choices give 4 distinct
    topologies from the same validated cut logic, instead of always the same
    "corridor at mid-height, LDK south, bedrooms north" layout:
      - `flip`: LDK band <-> bedroom band swap sides of the corridor
      - `axis`: corridor runs along the short axis (rotated 90deg) instead of
        always spanning the building's full width
    Both are exact reflections/rotations of the original tiling, so validity
    (tiling, connectivity, door/window thresholds) is preserved by construction.
    """
    A = q(rng.choice([8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 12.0]))
    B = q(rng.choice([7.5, 8.5, 9.0, 9.5, 10.0, 10.5]))
    axis = rng.choice(["horizontal", "horizontal", "vertical"])
    flip = rng.random() < 0.5

    # Build in a canonical local frame (corridor horizontal, LDK south) using
    # the original logic, then transform at the end per `axis`/`flip`.
    W, H = A, B
    bd = q(rng.uniform(2.5, 3.5))                 # bedroom depth (upper band)
    bd = min(bd, q(H - CW - MIN_DIM))             # keep lower band >= MIN_DIM
    yL = q(H - CW - bd)                           # lower (LDK) band height
    corridor = (0.0, yL, W, q(yL + CW))
    lower = (0.0, 0.0, W, yL)
    upper = (0.0, q(yL + CW), W, H)

    cells = [Cell(corridor, "hallway", is_corridor=True)]

    # LDK: 2-3 cells; largest = living-room, others kitchen/dining (open-joined).
    n_ldk = 3 if W >= 3 * MIN_DIM and rng.random() < 0.8 else 2
    ldk_rects = cut_band(lower, "x", n_ldk, rng)
    biggest = max(range(len(ldk_rects)), key=lambda i: area(ldk_rects[i]))
    side_types = ["kitchen", "dining-room", "kitchen"]
    si = 0
    for i, r in enumerate(ldk_rects):
        if i == biggest:
            cells.append(Cell(r, "living-room", ldk=True))
        else:
            cells.append(Cell(r, side_types[si % len(side_types)], ldk=True))
            si += 1

    # Bedrooms + bathroom off the corridor (vertical cuts -> all touch corridor).
    nb = max(2, target_rooms - len(ldk_rects) - 1)
    bed_rects = cut_band(upper, "x", nb, rng)
    smallest = min(range(len(bed_rects)), key=lambda i: area(bed_rects[i]))
    for i, r in enumerate(bed_rects):
        cells.append(Cell(r, "bathroom" if i == smallest else "bedroom"))

    if flip:
        cells = [Cell(_mirror_y(c.rect, H), c.type, c.ldk, c.is_corridor) for c in cells]
    if axis == "vertical":
        cells = [Cell(_transpose_rect(c.rect), c.type, c.ldk, c.is_corridor) for c in cells]
        W, H = H, W

    return cells, W, H


def build_office(rng: random.Random, target_rooms: int):
    branch_count = 1 if target_rooms < 26 else 2
    W = q(rng.choice([22.0, 24.0, 26.0, 28.0, 30.0]))
    H = q(rng.choice([12.0, 13.0, 14.0, 15.0, 16.0]))
    ys = q(H / 2 - CW / 2)
    cells = [Cell((0.0, ys, W, q(ys + CW)), "hallway", is_corridor=True)]

    # Vertical branch corridors (above + below the spine, so no spine overlap).
    seg = W / (branch_count + 1)
    branch_xs = []
    for i in range(1, branch_count + 1):
        bx = q(i * seg - CW / 2)
        branch_xs.append(bx)
        cells.append(Cell((bx, q(ys + CW), q(bx + CW), H), "hallway", is_corridor=True))
        cells.append(Cell((bx, 0.0, q(bx + CW), ys), "hallway", is_corridor=True))

    # Room bands = width not covered by branches, above and below the spine.
    bounds = [0.0]
    for bx in branch_xs:
        bounds += [bx, q(bx + CW)]
    bounds.append(W)
    room_segs = [(bounds[i], bounds[i + 1]) for i in range(0, len(bounds), 2)]

    rooms: list[Cell] = []
    for xa, xb in room_segs:
        if xb - xa < MIN_DIM:
            continue
        for sub in ((xa, q(ys + CW), xb, H), (xa, 0.0, xb, ys)):
            for r in cut_band(sub, "x", None, rng):
                rooms.append(Cell(r, "office"))

    # Type assignment by area: largest -> meeting, smallest -> restroom.
    order = sorted(range(len(rooms)), key=lambda i: area(rooms[i].rect), reverse=True)
    n_meet = max(1, len(rooms) // 8)
    n_rest = max(1, len(rooms) // 12)
    for i in order[:n_meet]:
        rooms[i].type = "meeting-room"
    for i in order[len(order) - n_rest:]:
        rooms[i].type = "restroom"
    cells.extend(rooms)

    return cells, W, H


def _modern_office_support_bar(W: float, y0: float, y1: float) -> list[Cell]:
    """Return the fixed, compact support programme along one circulation bar.

    Every support room has a full edge on the circulation band beneath it.  This
    is more robust than a nested core for Infinigen's door solver and still gives
    a recognizable contemporary office programme: large/small meeting, focus,
    break, restroom and storage/IT.
    """
    # The first five slots sum to 13 m.  Every supported footprint is at least
    # 15 m wide, so the final warehouse/IT slot is always >= MIN_DIM.
    widths = (4.0, 3.0, 2.0, 2.0, 2.0, q(W - 13.0))
    types = ("meeting-room", "meeting-room", "office", "break-room", "restroom", "warehouse")
    cells: list[Cell] = []
    x = 0.0
    for width, room_type in zip(widths, types):
        cells.append(Cell((q(x), y0, q(x + width), y1), room_type))
        x += width
    return cells


def _modern_office_base(rng: random.Random):
    W, H = rng.choice(MODERN_OFFICE_DIMENSIONS)
    topology = rng.choice(MODERN_OFFICE_TOPOLOGIES)
    support_depth = 3.5
    corridor_y0 = q(H - support_depth - CW)
    corridor_y1 = q(corridor_y0 + CW)
    support_y0 = corridor_y1
    cells: list[Cell] = [Cell((0.0, corridor_y0, W, corridor_y1), "hallway", is_corridor=True)]
    cells.extend(_modern_office_support_bar(W, support_y0, H))
    if topology == "split_neighborhood":
        # Two workspace clusters are open-connected; this preserves their visual
        # distinction without adding a second private-room corridor.
        split = q(W / 2.0)
        cells.append(Cell((0.0, 0.0, split, corridor_y0), "open-office", ldk=True))
        cells.append(Cell((split, 0.0, W, corridor_y0), "open-office", ldk=True))
    else:
        cells.append(Cell((0.0, 0.0, W, corridor_y0), "open-office"))
    if topology == "side_core":
        cells = [Cell(_transpose_rect(cell.rect), cell.type, cell.ldk, cell.is_corridor) for cell in cells]
        W, H = H, W
    return cells, W, H, topology


def build_modern_office(rng: random.Random):
    """Build a 180–300 m² contemporary hybrid office suite.

    Layout topology changes with the seed but all variants retain the same
    programme and a short, bounded circulation spine.  This replaces the
    user-facing office generator; the legacy :func:`build_office` stays intact
    for old output reproducibility.
    """
    return _modern_office_base(rng)


def modern_office_metadata(seed: int) -> dict:
    """Stable provenance summary written next to generated modern-office plans."""
    rng = random.Random(int(seed) * 1000)
    cells, W, H, topology = _modern_office_base(rng)
    counts: dict[str, int] = {}
    areas: dict[str, float] = {}
    for cell in cells:
        counts[cell.type] = counts.get(cell.type, 0) + 1
        areas[cell.type] = round(areas.get(cell.type, 0.0) + area(cell.rect), 3)
    return {
        "profile": MODERN_OFFICE_PROFILE,
        "archetype": MODERN_OFFICE_ARCHETYPE,
        "topology": topology,
        "footprint_m": [W, H],
        "footprint_area_m2": round(W * H, 3),
        "program_counts": counts,
        "program_area_m2": areas,
        "glass_partition_policy": "structural_blender_postprocess_v1",
        "requested_glass_partition_count": MODERN_GLASS_PARTITION_COUNT,
    }


def _segment_endpoints(shared):
    orient, const, lo, hi, _length = shared
    if orient == "v":
        return [[const, lo], [const, hi]]
    return [[lo, const], [hi, const]]


def modern_office_partition_spec(seed: int, count: int = MODERN_GLASS_PARTITION_COUNT) -> dict:
    """Return the deterministic structural-glass contract for a modern office.

    The candidates are private support rooms facing the circulation spine.  A
    full wall segment is exchanged for two glass panes around its already
    emitted door opening, so the room connection remains physically usable.
    This deliberately derives identity from the generated plan rather than
    Blender object ordering.
    """
    if count < 1:
        raise ValueError("modern glass partition count must be positive")
    plan = build_floor_plan(int(seed), MODERN_OFFICE_ARCHETYPE)
    rects = {name: _parse_box(spec["shape"]) for name, spec in plan["rooms"].items()}
    priority = {"meeting-room": 0, "office": 1, "break-room": 2}
    candidates = []
    for door_id, door in plan["doors"].items():
        p0, p1 = _parse_line(door["shape"])
        touched = []
        for name, rect in rects.items():
            x0, y0, x1, y1 = rect
            if abs(p0[0] - p1[0]) < 1e-6:
                if abs(x0 - p0[0]) < 1e-6 or abs(x1 - p0[0]) < 1e-6:
                    if min(y1, max(p0[1], p1[1])) - max(y0, min(p0[1], p1[1])) > 1e-6:
                        touched.append(name)
            elif abs(y0 - p0[1]) < 1e-6 or abs(y1 - p0[1]) < 1e-6:
                if min(x1, max(p0[0], p1[0])) - max(x0, min(p0[0], p1[0])) > 1e-6:
                    touched.append(name)
        corridor = next((name for name in touched if name.startswith("hallway_")), None)
        room = next((name for name in touched if name.split("_")[0] in priority), None)
        if not corridor or not room:
            continue
        edge = shared_edge(rects[corridor], rects[room])
        if not edge:
            continue
        candidates.append({
            "room": room, "corridor": corridor, "door_id": door_id,
            "priority": priority[room.split("_")[0]],
            "wall_endpoints_m": _segment_endpoints(edge),
            "orientation": "vertical" if edge[0] == "v" else "horizontal",
            "door_opening_m": [[p0[0], p0[1]], [p1[0], p1[1]]],
        })
    candidates.sort(key=lambda item: (item["priority"], item["room"], item["door_id"]))
    if len(candidates) < count:
        raise ValueError(
            f"modern_glass_v1 requires {count} eligible support-wall segments; found {len(candidates)}"
        )
    selected = []
    for index, item in enumerate(candidates[:count], 1):
        selected.append({
            "segment_id": f"office_glass_{index:02d}",
            **{key: value for key, value in item.items() if key != "priority"},
            "frame": {"profile_m": 0.04, "top_clearance_m": 0.10},
        })
    core = {
        "schema": "robomituba.opticalnav_modern_glass_spec.v1",
        "requested_partition_count": count,
        "eligible_segment_count": len(candidates),
        "selected_segment_ids": [item["segment_id"] for item in selected],
        "segments": selected,
    }
    core["digest"] = hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return core


def build_single_room(rng: random.Random, room_type: str):
    """Build one furnished-room semantic with an entrance and exterior window.

    The floor plan intentionally contains no terrain or outdoor geometry. The
    window is a stable optical opening; a later Mitsuba environment-map policy
    supplies the view outside it without inflating the Infinigen scene.
    """
    room_type = room_type.replace("_", "-")
    if room_type not in SINGLE_ROOM_PROFILES:
        raise ValueError(f"unknown single-room type {room_type!r}; have {SINGLE_ROOM_TYPES}")
    profile = SINGLE_ROOM_PROFILES[room_type]
    width, depth = rng.choice(profile["sizes"])
    width, depth = q(width), q(depth)
    room = (0.0, 0.0, width, depth)

    # Put the entrance on the south wall and the window on the opposite wall,
    # ensuring a walkable route and an unobstructed exterior ray direction.
    door_width = min(DOOR_W, q(width - 2 * UNIT))
    door_x = q((width - door_width) * 0.25)
    window_width = min(float(profile["window_width"]), q(width - 2 * UNIT))
    window_x = q((width - window_width) * 0.5)
    window = {"shape": _line_str((window_x, depth), (q(window_x + window_width), depth))}
    if profile["panoramic"]:
        window["is_panoramic"] = 1

    return [Cell(room, room_type)], width, depth, {
        "doors": {
            "door": {"shape": _line_str((door_x, 0.0), (q(door_x + door_width), 0.0))}
        },
        "windows": {"window": window},
    }


# --- emission --------------------------------------------------------------


def _connection_kind(a: Cell, b: Cell):
    if a.is_corridor and b.is_corridor:
        return "open"          # merge corridor network into one circulation space
    if a.is_corridor != b.is_corridor:
        room = b if a.is_corridor else a
        if room.ldk and room.type != "living-room":
            return None        # non-living LDK reaches corridor via opens, not a door
        return "door"
    if a.ldk and b.ldk:
        return "open"          # open LDK between living/kitchen/dining
    return None                # two private rooms: no direct door (use corridor)


def _exterior_sides(r: Rect, W: float, H: float):
    x0, y0, x1, y1 = r
    out = []
    if x0 == 0.0:
        out.append(("v", 0.0, y0, y1))
    if x1 == W:
        out.append(("v", W, y0, y1))
    if y0 == 0.0:
        out.append(("h", 0.0, x0, x1))
    if y1 == H:
        out.append(("h", H, x0, x1))
    return out


def emit(cells: list[Cell], W: float, H: float, rng: random.Random) -> dict:
    counters: dict[str, int] = {}
    for c in cells:
        i = counters.get(c.type, 0)
        counters[c.type] = i + 1
        c.name = f"{c.type}_0/{i}"

    rooms = {c.name: {"shape": _box_str(c.rect)} for c in cells}
    doors: dict[str, dict] = {}
    opens: dict[str, dict] = {}
    windows: dict[str, dict] = {}

    def _key(d, base):
        return base if base not in d else f"{base}.{len(d):03d}"

    # doors / opens between adjacent cells
    for i in range(len(cells)):
        for j in range(i + 1, len(cells)):
            se = shared_edge(cells[i].rect, cells[j].rect)
            if not se:
                continue
            orient, const, lo, hi, length = se
            kind = _connection_kind(cells[i], cells[j])
            if kind == "door" and length < DOOR_MIN:
                continue
            if kind == "open" and length <= MARGIN:
                continue
            if kind is None:
                continue
            width = DOOR_W if kind == "door" else OPEN_W
            p0, p1 = _centered_line(orient, const, lo, hi, width)
            tgt, base = (doors, "door") if kind == "door" else (opens, "open")
            tgt[_key(tgt, base)] = {"shape": _line_str(p0, p1)}

    # unit entrance: a door on a corridor's exterior wall
    for c in cells:
        if not c.is_corridor:
            continue
        ext = [s for s in _exterior_sides(c.rect, W, H) if (s[3] - s[2]) > DOOR_MIN]
        if ext:
            orient, const, lo, hi = ext[0]
            p0, p1 = _centered_line(orient, const, lo, hi, DOOR_W)
            doors[_key(doors, "door")] = {"shape": _line_str(p0, p1)}
            break

    # windows: one per room on its longest exterior edge.  Contemporary office
    # work areas receive the same large facade glazing treatment as a living
    # room, making the exterior-facing workspace visually legible in renders.
    for c in cells:
        if c.is_corridor:
            continue
        ext = [s for s in _exterior_sides(c.rect, W, H) if (s[3] - s[2]) >= WIN_MIN]
        if not ext:
            continue
        orient, const, lo, hi = max(ext, key=lambda s: s[3] - s[2])
        p0, p1 = _centered_line(orient, const, lo, hi, min(WIN_MAX, (hi - lo) - 0.5))
        entry = {"shape": _line_str(p0, p1)}
        if c.type in {"living-room", "open-office"}:
            entry["is_panoramic"] = 1
        windows[_key(windows, "window")] = entry

    return {"rooms": rooms, "doors": doors, "opens": opens,
            "interiors": {}, "windows": windows}


# --- validation (pure python, always runs) ---------------------------------

_BOX_RE = re.compile(
    r"shapely\.box\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)")
_NAME_RE = re.compile(r"^[a-z][a-z-]*_\d+/\d+$")
_VALID_TYPES = set(SINGLE_ROOM_TYPES)
_LINE_RE = re.compile(r"\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)")


def _parse_box(s: str) -> Rect:
    m = _BOX_RE.search(s)
    return tuple(float(m.group(i)) for i in range(1, 5))


def _parse_line(s: str):
    return [(float(a), float(b)) for a, b in _LINE_RE.findall(s)]


def validate_plan(plan: dict) -> list[str]:
    """Pure-python invariant check. Returns [] if valid, else error strings."""
    errs: list[str] = []
    names = list(plan["rooms"])
    rects = {n: _parse_box(plan["rooms"][n]["shape"]) for n in names}

    # naming + types
    for n in names:
        if not _NAME_RE.match(n):
            errs.append(f"bad room name: {n!r}")
        if n.split("_")[0] not in _VALID_TYPES:
            errs.append(f"unknown room type in {n!r}")

    # no overlaps
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if overlap_area(rects[names[i]], rects[names[j]]) > 0.01:
                errs.append(f"overlap: {names[i]} & {names[j]}")

    # exact tiling of the bounding box (no gaps): sum(area) == bbox area
    x0 = min(r[0] for r in rects.values())
    y0 = min(r[1] for r in rects.values())
    x1 = max(r[2] for r in rects.values())
    y1 = max(r[3] for r in rects.values())
    bbox = (x1 - x0) * (y1 - y0)
    total = sum(area(r) for r in rects.values())
    if abs(total - bbox) > 0.01:
        errs.append(f"not tiling: sum(area)={total:.3f} != bbox={bbox:.3f}")

    # connectivity via emitted doors + opens (every room reachable)
    adj: dict[str, set] = {n: set() for n in names}

    def _incident(line_pts):
        (ax, ay), (bx, by) = line_pts[0], line_pts[-1]
        vert = abs(ax - bx) < 1e-6
        const = ax if vert else ay
        lo, hi = (min(ay, by), max(ay, by)) if vert else (min(ax, bx), max(ax, bx))
        hit = []
        for n, r in rects.items():
            if vert and (abs(r[0] - const) < 1e-6 or abs(r[2] - const) < 1e-6):
                if min(r[3], hi) - max(r[1], lo) > 1e-6:
                    hit.append(n)
            elif not vert and (abs(r[1] - const) < 1e-6 or abs(r[3] - const) < 1e-6):
                if min(r[2], hi) - max(r[0], lo) > 1e-6:
                    hit.append(n)
        return hit

    for grp in ("doors", "opens"):
        for spec in plan[grp].values():
            hit = _incident(_parse_line(spec["shape"]))
            for a in hit:
                for b in hit:
                    if a != b:
                        adj[a].add(b)

    seen, stack = set(), [names[0]]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(adj[cur] - seen)
    if len(seen) != len(names):
        errs.append(f"disconnected: {len(seen)}/{len(names)} rooms reachable")

    return errs


def validate_plan_shapely(plan: dict):
    """Optional cross-check using Infinigen's own exterior=union_all step.
    Returns 'skipped' if shapely is unavailable, [] if valid, else errors."""
    try:
        import shapely
    except ImportError:
        return "skipped"
    errs = []
    ns = {"shapely": shapely}
    polys = [eval(spec["shape"], ns) for spec in plan["rooms"].values()]  # noqa: S307
    union = shapely.union_all(polys)
    if union.geom_type != "Polygon":
        errs.append(f"exterior is {union.geom_type} (gap/disconnect), expected Polygon")
    if abs(union.area - sum(p.area for p in polys)) > 0.01:
        errs.append("union area != sum(room areas) (overlap or gap)")
    return errs


# --- top-level entry -------------------------------------------------------


def build_floor_plan(seed: int, archetype: str, target_rooms: int | None = None) -> dict:
    """Deterministically build a VALID Infinigen floor-plan dict for (seed,
    archetype). Retries with perturbed sub-seeds if a draw yields a sliver."""
    errs: list[str] = []
    for attempt in range(8):
        rng = random.Random(int(seed) * 1000 + attempt)
        if archetype == "apartment":
            tr = target_rooms or rng.randint(5, 10)
            cells, W, H = build_apartment(rng, tr)
        elif archetype == "office":
            tr = target_rooms or rng.randint(20, 40)
            cells, W, H = build_office(rng, tr)
        elif archetype == MODERN_OFFICE_ARCHETYPE:
            cells, W, H, _topology = build_modern_office(rng)
        elif archetype == "single_room":
            raise ValueError("single_room requires build_single_room_plan(seed, room_type)")
        else:
            raise ValueError(f"unknown archetype {archetype!r}")
        plan = emit(cells, W, H, rng)
        errs = validate_plan(plan)
        if not errs:
            return plan
    raise ValueError(
        f"floorplan_gen: no valid plan for seed={seed} archetype={archetype}: {errs}")


def build_single_room_plan(seed: int, room_type: str) -> dict:
    """Build and validate one deterministic room plan for an Infinigen scene."""
    canonical = room_type.replace("_", "-")
    if canonical not in SINGLE_ROOM_TYPES:
        raise ValueError(f"unknown single-room type {room_type!r}; have {SINGLE_ROOM_TYPES}")
    rng = random.Random(int(seed) * 1000 + 17)
    cells, W, H, openings = build_single_room(rng, canonical)
    plan = emit(cells, W, H, rng)
    plan["doors"] = openings["doors"]
    plan["windows"] = openings["windows"]
    errs = validate_plan(plan)
    if errs:
        raise ValueError(f"single-room floorplan invalid for seed={seed} type={canonical}: {errs}")
    return plan


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Dump a generated floor plan as JSON.")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--archetype", choices=["apartment", "office", "single_room"], default="apartment")
    ap.add_argument("--room-type", choices=SINGLE_ROOM_TYPES, default="living-room")
    ap.add_argument("--rooms", type=int, default=None)
    a = ap.parse_args()
    plan = (build_single_room_plan(a.seed, a.room_type)
            if a.archetype == "single_room"
            else build_floor_plan(a.seed, a.archetype, a.rooms))
    print(json.dumps(plan, indent=2))
    print("# rooms:", len(plan["rooms"]), "doors:", len(plan["doors"]),
          "opens:", len(plan["opens"]), "windows:", len(plan["windows"]))
    print("# validate_plan:", validate_plan(plan) or "OK")
    print("# validate_shapely:", validate_plan_shapely(plan))
