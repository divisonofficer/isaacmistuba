#!/usr/bin/env python3
"""Seed-driven procedural floor-plan generator for Infinigen indoor scenes.

Emits the same floor-plan dict that ``infinigen_gen.py``'s hand-authored builders
produce (rooms / doors / opens / interiors / windows, each ``{"shape": "<shapely
expr string>"}``), but *generated* from a seed so every plan differs while staying
VALID for Infinigen's solver.

Two archetypes:
  - "apartment": living-room-centered, one central corridor band, open LDK
    (living/kitchen/dining joined by ``opens``), bedrooms + bathroom off the
    corridor. Hub-and-spoke nav graph.
  - "office": a corridor network (full-width spine + vertical branches) with many
    small rooms budding off the corridors; rooms at spine x branch junctions touch
    two corridors -> varied entry counts.

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
    W = q(rng.choice([8.5, 9.0, 9.5, 10.0, 10.5, 11.0]))
    H = q(rng.choice([8.5, 9.0, 9.5, 10.0, 10.5]))
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

    # windows: one per room on its longest exterior edge; living-room panoramic
    for c in cells:
        if c.is_corridor:
            continue
        ext = [s for s in _exterior_sides(c.rect, W, H) if (s[3] - s[2]) >= WIN_MIN]
        if not ext:
            continue
        orient, const, lo, hi = max(ext, key=lambda s: s[3] - s[2])
        p0, p1 = _centered_line(orient, const, lo, hi, min(WIN_MAX, (hi - lo) - 0.5))
        entry = {"shape": _line_str(p0, p1)}
        if c.type == "living-room":
            entry["is_panoramic"] = 1
        windows[_key(windows, "window")] = entry

    return {"rooms": rooms, "doors": doors, "opens": opens,
            "interiors": {}, "windows": windows}


# --- validation (pure python, always runs) ---------------------------------

_BOX_RE = re.compile(
    r"shapely\.box\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)")
_NAME_RE = re.compile(r"^[a-z][a-z-]*_\d+/\d+$")
_VALID_TYPES = {
    "living-room", "kitchen", "dining-room", "bedroom", "bathroom", "hallway",
    "closet", "office", "meeting-room", "open-office", "break-room", "restroom",
    "utility", "balcony", "garage",
}
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
            tr = target_rooms or rng.randint(6, 9)
            cells, W, H = build_apartment(rng, tr)
        elif archetype == "office":
            tr = target_rooms or rng.randint(20, 40)
            cells, W, H = build_office(rng, tr)
        else:
            raise ValueError(f"unknown archetype {archetype!r}")
        plan = emit(cells, W, H, rng)
        errs = validate_plan(plan)
        if not errs:
            return plan
    raise ValueError(
        f"floorplan_gen: no valid plan for seed={seed} archetype={archetype}: {errs}")


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Dump a generated floor plan as JSON.")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--archetype", choices=["apartment", "office"], default="apartment")
    ap.add_argument("--rooms", type=int, default=None)
    a = ap.parse_args()
    plan = build_floor_plan(a.seed, a.archetype, a.rooms)
    print(json.dumps(plan, indent=2))
    print("# rooms:", len(plan["rooms"]), "doors:", len(plan["doors"]),
          "opens:", len(plan["opens"]), "windows:", len(plan["windows"]))
    print("# validate_plan:", validate_plan(plan) or "OK")
    print("# validate_shapely:", validate_plan_shapely(plan))
