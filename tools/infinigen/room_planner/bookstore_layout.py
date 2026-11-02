"""Deterministic floor layout for the underground bookstore (docs/bookstore_underground_design_proposal.md). No bpy.

    plan = layout(x0, x1, y0, y1, seed)      # world box of the room -> {"islands": [...], "wall_shelves": [...], "signs": [...], "popups": [...]}

Each entry: {"x", "y", "yaw", "cat", "zone"}. Conventions match proc_bookstore: a piece's front is +X, so an island (length along its local y) needs
yaw = pi/2 when the room's long axis is x. Rules: wall shelving (2.4 x 0.35 m) along the two long walls and the back wall; islands in rows
parallel to the long axis (2.4 x 1.0 m, 0.6 m gap, a 1.8 m cross aisle every 4 islands), aisles 1.7 m; the first 4.5 m from the entrance (u = 0)
stay open for pop-up / new-arrival tables; a section sign at the end of every row. Zones (A new, B test-prep, C cooking/hobby, D stationery) are
assigned by row so the LLM / plan can name them.
"""
from __future__ import annotations

import math
import random

ISLAND_L, ISLAND_D, SHELF_W, SHELF_D = 2.4, 1.0, 2.4, 0.35
DOOR_CLEAR = 2.2                                                  # used by realize._why_not_placed
SIZE = {"book_island": (ISLAND_D, ISLAND_L), "book_wall_shelf": (SHELF_D, SHELF_W), "section_sign": (0.26, 0.37), "pop_stand": (0.5, 0.6), "wall_poster": (0.06, 0.86), "bestseller_table": (ISLAND_D, ISLAND_L), "bestseller_sign": (0.26, 0.37)}
AISLE, GAP, CROSS_EVERY, ENTRANCE = 1.7, 0.6, 4, 4.5
ZONES = ("A", "B", "C", "D")


def layout(x0, x1, y0, y1, seed=0, obstacles=(), doors=()):
    rng = random.Random(seed)
    W, D = x1 - x0, y1 - y0
    long_x = W >= D
    L, S = (W, D) if long_x else (D, W)

    def world(u, v):                                          # u along the long axis from the entrance end, v across
        return (x0 + u, y0 + v) if long_x else (x0 + v, y0 + u)

    face = lambda u_dir, v_dir: None                          # (kept simple: yaw computed per piece below)
    out = {"islands": [], "wall_shelves": [], "signs": [], "popups": [], "long_axis": "x" if long_x else "y"}
    # wall shelving: long walls (v = 0 and v = S) and the back wall (u = L); their front points into the room
    def shelf_yaw(nu, nv):                                    # inward normal (in u, v) -> yaw of a piece whose front is +X
        nx, ny = (nu, nv) if long_x else (nv, nu)
        return math.atan2(ny, nx)
    for v, nv in ((SHELF_D / 2 + 0.14, 1), (S - SHELF_D / 2 - 0.14, -1)):     # 0.14 m off the wall: shelves 0.2 m from it were refused 'off_floor'
        u = ENTRANCE
        while u + SHELF_W <= L - SHELF_D:
            cx, cy = world(u + SHELF_W / 2, v)
            out["wall_shelves"].append({"x": cx, "y": cy, "yaw": shelf_yaw(0, nv), "cat": "book_wall_shelf", "zone": "B"})
            u += SHELF_W
    v = SHELF_D + 0.0
    while v + SHELF_W <= S - SHELF_D:                         # back wall
        cx, cy = world(L - SHELF_D / 2 - 0.14, v + SHELF_W / 2)
        out["wall_shelves"].append({"x": cx, "y": cy, "yaw": shelf_yaw(-1, 0), "cat": "book_wall_shelf", "zone": "B"})
        v += SHELF_W
    # island rows
    clear = SHELF_D + 0.14 + AISLE + 0.3        # the first island row clears the wall shelves' footprint (bookstore r2: 5 'obstacle')
    v_lo, v_hi = clear, S - clear
    pitch = ISLAND_D + AISLE
    nrows = max(0, int((v_hi - v_lo + AISLE) // pitch))
    v_start = v_lo + ISLAND_D / 2 + ((v_hi - v_lo) - (nrows * pitch - AISLE)) / 2
    island_yaw = math.pi / 2 if long_x else 0.0               # length along the long axis
    for r in range(nrows):
        v = v_start + r * pitch
        zone = ZONES[r % len(ZONES)]
        u, k = ENTRANCE, 0
        first = None
        while u + ISLAND_L <= L - SHELF_D - AISLE:
            cx, cy = world(u + ISLAND_L / 2, v)
            out["islands"].append({"x": cx, "y": cy, "yaw": island_yaw, "cat": "book_island", "zone": zone, "row": r})
            first = first or (u, v)
            u += ISLAND_L + GAP
            k += 1
            if k % CROSS_EVERY == 0:
                u += AISLE - GAP
        if first:                                             # a sign at the row's entrance end, facing the entrance
            sx, sy = world(first[0] - 0.4, first[1])
            out["signs"].append({"x": sx, "y": sy, "yaw": shelf_yaw(-1, 0), "cat": "section_sign", "zone": zone, "row": r})
    # pop-up / new-arrival tables in the open entrance zone: short rows of the same island
    for r in range(max(1, nrows)):
        v = v_start + r * pitch
        u = 1.2
        while u + ISLAND_L <= ENTRANCE - 0.6:
            cx, cy = world(u + ISLAND_L / 2, v)
            out["popups"].append({"x": cx, "y": cy, "yaw": island_yaw, "cat": "book_island", "zone": "A", "row": r})
            u += ISLAND_L + GAP
    rng.shuffle(out["popups"])
    out["popups"] = out["popups"][: max(2, len(out["popups"]) * 2 // 3)]
    # promotion stands: a row across the open entrance zone (the first 4 m) and one at the head of every second island row
    out["pop_stands"] = []
    for k in range(max(2, int((S - 2.0) / 3.0))):
        cx, cy = world(ENTRANCE - 1.1, 1.5 + k * 3.0)
        if cy is not None and 1.5 + k * 3.0 < S - 1.0:
            out["pop_stands"].append({"x": cx, "y": cy, "yaw": shelf_yaw(1, 0), "cat": "pop_stand", "zone": "A"})
    # bestseller table: one of the pop-up islands, with its own sign at the entrance end; ad posters on the two long walls in the shelf-free entrance zone
    out["bestsellers"], out["best_signs"], out["posters"] = [], [], []
    if out["popups"]:
        b = out["popups"].pop(0); out["bestsellers"].append({**b, "cat": "bestseller_table"})
        sx, sy = (b["x"] - 1.7, b["y"]) if long_x else (b["x"], b["y"] - 1.7)          # at the entrance end of the table
        out["best_signs"].append({"x": sx, "y": sy, "yaw": shelf_yaw(-1, 0), "cat": "bestseller_sign", "zone": "A"})
    for v, nv in ((0.06, 1), (S - 0.06, -1)):
        for u in (1.0, 2.4, 3.8):
            cx, cy = world(u, v)
            out["posters"].append({"x": cx, "y": cy, "yaw": shelf_yaw(0, nv), "cat": "wall_poster", "zone": "A", "lift": 0.9})
    # keep doors and columns clear: drop what stands within DOOR_CLEAR of a door or on an obstacle footprint (x0, x1, y0, y1), padded
    def clear(e):
        if any(abs(e["x"] - dx) < 2.2 and abs(e["y"] - dy) < 2.2 for dx, dy in doors):
            return False
        return not any(o[0] - 0.8 < e["x"] < o[1] + 0.8 and o[2] - 0.8 < e["y"] < o[3] + 0.8 for o in obstacles)
    for key in ("islands", "wall_shelves", "signs", "popups", "pop_stands", "bestsellers", "best_signs", "posters"):
        out[key] = [e for e in out[key] if clear(e)]
    return out


if __name__ == "__main__":
    import sys
    W, D = (float(a) for a in (sys.argv[1:3] or (30, 22)))
    p = layout(0, W, 0, D, 1)
    print({k: len(v) for k, v in p.items() if isinstance(v, list)}, "long axis", p["long_axis"])
    # coarse ASCII map, 1 char = 1 m
    g = [["." for _ in range(int(W))] for _ in range(int(D))]
    for key, ch in (("wall_shelves", "#"), ("islands", "I"), ("popups", "P"), ("signs", "s")):
        for e in p[key]:
            if 0 <= int(e["y"]) < int(D) and 0 <= int(e["x"]) < int(W):
                g[int(e["y"])][int(e["x"])] = ch
    print("\n".join("".join(r) for r in g))
    books = len(p["islands"]) * 460 + len(p["popups"]) * 460 + len(p["wall_shelves"]) * 500
    print("approx books", books, "approx tris", books * 12)
