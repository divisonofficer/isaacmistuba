"""Deterministic layout of the university cafeteria hall (S27, ROOM_MODE=cafeteria; docs/cafeteria_school_design_proposal.md). No bpy.

    layout(x0, x1, y0, y1, seed, obstacles=(), doors=()) -> {"items": [...], "hung": [...]}

Long axis u: a serving line along the wall v = 0 (u 1.5 .. L - 5), a menu board above it, one UV-trap column on the axis, rows of long oak tables parallel to the long axis (3.6 m, 4 plywood chairs
a side, rows 2.6 m apart, started 3.2 m from the serving wall), a diamond pendant over every 1.2 m of every table. Doors are kept clear (1.8 m).
"""
from __future__ import annotations

import math
import random

CATS = {"serving": "serving_line", "table": "long_oak_table", "chair": "ply_shell_chair", "column": "uv_trap_column", "menu": "menu_board", "pendant": "diamond_pendant"}
DROP = {"cafe_table", "cafe_chair", "bar_stool", "window_bar", "banquette_row", "banquette", "counter", "backbar_shelf", "break_table", "break_chair"}


def layout(x0, x1, y0, y1, seed=0, obstacles=(), doors=()):
    rng = random.Random(seed)
    W, D = x1 - x0, y1 - y0
    long_x = W >= D
    L, S = (W, D) if long_x else (D, W)
    world = (lambda u, v: (x0 + u, y0 + v)) if long_x else (lambda u, v: (x0 + v, y0 + u))
    yaw_of = lambda nu, nv: math.atan2(*((nv, nu) if long_x else (nu, nv)))
    items, hung = [], []
    near_door = lambda x, y, r=1.8: any(abs(x - dx) < r and abs(y - dy) < r for dx, dy in doors)
    # serving line along v = 0, facing the hall (+v); a menu board above it on the wall
    sl = min(7.0, L - 7.0)
    x, y = world(1.5 + sl / 2, 0.55)
    items.append({"cat": "serving", "x": round(x, 3), "y": round(y, 3), "yaw": round(yaw_of(0, 1), 4)})
    x, y = world(1.5 + sl / 2, 0.06)
    items.append({"cat": "menu", "x": round(x, 3), "y": round(y, 3), "yaw": round(yaw_of(0, 1), 4), "direct": True, "lift": 1.7})
    # the UV-trap column at mid-length on the axis
    uc, vc = L * 0.5, S * 0.55
    x, y = world(uc, vc)
    items.append({"cat": "column", "x": round(x, 3), "y": round(y, 3), "yaw": 0.0})
    # rows of long tables, each with 4 chairs a side
    n_rows = max(1, int((S - 3.2 - 1.0) // 2.6))
    for rw in range(n_rows):
        v = 3.2 + 1.0 + rw * 2.6
        u = 2.2
        while u + 3.6 <= L - 1.2:
            xc, yc = world(u + 1.8, v)
            if abs(u + 1.8 - uc) < 2.6 and abs(v - vc) < 1.4:           # not through the column
                u += 4.0; continue
            if near_door(xc, yc, 2.2):
                u += 4.0; continue
            items.append({"cat": "table", "x": round(xc, 3), "y": round(yc, 3), "yaw": round(math.pi / 2 if long_x else 0.0, 4)})
            for du in (-1.35, -0.45, 0.45, 1.35):
                for dv, face in ((-0.68, 1), (0.68, -1)):
                    cx, cy = world(u + 1.8 + du, v + dv)
                    items.append({"cat": "chair", "x": round(cx, 3), "y": round(cy, 3), "yaw": round(yaw_of(0, face), 4), "direct": True})      # tucked at the table edge: the footprint check refused all 80 (S27 r3)
            for du in (-1.2, 0.0, 1.2):
                px, py = world(u + 1.8 + du, v)
                hung.append({"cat": "pendant", "x": round(px, 3), "y": round(py, 3), "drop": 1.0})
            u += 4.0
    return {"items": items, "hung": hung}


if __name__ == "__main__":
    import collections
    p = layout(0, 20, 0, 12, 1, doors=[(0.0, 6.0)])
    print(dict(collections.Counter(e["cat"] for e in p["items"])), "hung", len(p["hung"]))
