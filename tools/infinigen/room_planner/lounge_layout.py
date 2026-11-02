"""Deterministic layout of the LP-cafe building lounge (S29, ROOM_MODE=lounge; docs/lounge_lp_cafe_design_proposal.md). No bpy.

    layout(x0, x1, y0, y1, seed, obstacles=(), doors=()) -> {"items": [...], "hung": [...]}

Long axis u from the entrance end: an LP wall (grid shelving units 2.4 m, 60-75 % of the long wall v = S), an elevator hall on the short wall u = L (two elevator doors + exit sign), a zone of red
high tables with oak stools (2-3 tables, 4 stools each) in the first 7 m, an amber round pendant over each table. Wall pieces are placed `direct` (flush); `lift` = mounting height.
"""
from __future__ import annotations

import math
import os
import random

CATS = {"lp_shelf": "lp_shelf", "high_table": "red_high_table", "long_table": "red_high_table_long", "stool": "wood_stool", "pendant": "round_pendant", "elevator": "elevator_door", "exit": "exit_sign", "casual_table": "cafe_table", "casual_chair": "cafe_chair"}
DROP = {"cafe_table", "cafe_chair", "bar_stool", "window_bar", "banquette_row", "banquette", "bookshelf", "bookcase"}   # the plan coffee bar (counter + back-bar shelf) STAYS: the reference lounge has one


def layout(x0, x1, y0, y1, seed=0, obstacles=(), doors=()):
    rng = random.Random(seed)
    W, D = x1 - x0, y1 - y0
    long_x = W >= D
    L, S = (W, D) if long_x else (D, W)
    world = (lambda u, v: (x0 + u, y0 + v)) if long_x else (lambda u, v: (x0 + v, y0 + u))
    yaw_of = lambda nu, nv: math.atan2(*((nv, nu) if long_x else (nu, nv)))       # inward normal (u, v) -> yaw of a piece whose front is +X
    items, hung = [], []
    far_free = lambda x, y: not any(abs(x - dx) < 1.4 and abs(y - dy) < 1.4 for dx, dy in doors)
    # LP wall along v = S: contiguous 3.0 m units (2.7 m high) from u = 1.5 to L - 3.0. Pilasters on that wall (S29F: 0.26 m deep, every 3.8 m) made every unit fail _place (4 of 4, r6), so the wall
    # is placed `direct`, its back pushed out to the pilaster fronts, and the pilasters disappear behind the display.
    back = 0.0
    for c in obstacles:                                                           # (xmin, xmax, ymin, ymax) footprints of columns / pilasters
        v0, v1 = (c[2] - y0, c[3] - y0) if long_x else (c[0] - x0, c[1] - x0)
        if v1 > S - 0.15 and v0 > S - 0.8:
            back = max(back, S - v0)
    if os.environ.get("ROOM_LOUNGE_LPWALL") == "1":
        for k in range(max(1, int((L - 4.5) // 3.0))):
            x, y = world(3.0 + 3.0 * k, S - back - 0.01)
            if far_free(x, y):
                items.append({"cat": "lp_shelf", "x": round(x, 3), "y": round(y, 3), "yaw": round(yaw_of(0, -1), 4), "direct": True})
    else:                                                                          # the S29 single-room layout, unchanged
        n_units = max(1, int(rng.uniform(0.85, 1.0) * (L - 4.5) // 3.05))
        u = 1.5
        for k in range(n_units):
            x, y = world(u + 1.5, S - 0.3)
            if far_free(x, y):
                items.append({"cat": "lp_shelf", "x": round(x, 3), "y": round(y, 3), "yaw": round(yaw_of(0, -1), 4)})
            u += 3.05
    # elevator hall on the short wall u = L
    for dv in (-0.8, 0.8):
        x, y = world(L - 0.035, S / 2 + dv)
        items.append({"cat": "elevator", "x": round(x, 3), "y": round(y, 3), "yaw": round(yaw_of(-1, 0), 4), "direct": True})
    x, y = world(L - 0.035, S / 2 + 2.6)
    items.append({"cat": "exit", "x": round(x, 3), "y": round(y, 3), "yaw": round(yaw_of(-1, 0), 4), "direct": True, "lift": 2.3})
    # LP lounge reference plan: TWO LONG red high tables (4.8 m, stools on both sides) side by side in the entrance-side half, against the wall OPPOSITE the LP display; a hall too short or narrow
    # for 4.8 m tables keeps the old 2-3 short tables. The middle and the LP side stay an open walkway.
    long_ok = L >= 11.0 and S >= 7.0
    if long_ok:
        for k in range(2):
            v = 1.5 + 2.1 * k
            ux = 5.0                                                           # table centre along u (spans u 2.6 .. 7.4)
            x, y = world(ux, v)
            if not far_free(x, y):
                continue
            items.append({"cat": "long_table", "x": round(x, 3), "y": round(y, 3), "yaw": round(math.pi / 2 if long_x else 0.0, 4)})
            for j in range(6):
                du = -2.1 + j * 0.84
                for dv in (-0.62, 0.62):
                    sx, sy = world(ux + du, v + dv)
                    items.append({"cat": "stool", "x": round(sx, 3), "y": round(sy, 3), "yaw": round(yaw_of(0, 1 if dv < 0 else -1), 4)})
            for du in (-1.6, 0.0, 1.6):
                px, py = world(ux + du, v)
                hung.append({"cat": "pendant", "x": round(px, 3), "y": round(py, 3), "drop": 0.9})
    else:
        n_t = 3 if S >= 8.5 else 2
        for k in range(n_t):
            v = 1.2 + 2.0 * k
            if v > 0.45 * S:
                break
            x, y = world(3.6, v)
            if not far_free(x, y):
                continue
            yaw_t = math.pi / 2 if long_x else 0.0
            items.append({"cat": "high_table", "x": round(x, 3), "y": round(y, 3), "yaw": round(yaw_t, 4)})
            for du in (-0.8, 0.8):
                for dv in (-0.62, 0.62):
                    sx, sy = world(3.6 + du, v + dv)
                    items.append({"cat": "stool", "x": round(sx, 3), "y": round(sy, 3), "yaw": round(yaw_of(0, 1 if dv < 0 else -1), 4)})
            for du in (-0.8, 0.8):
                px, py = world(3.6 + du, v)
                hung.append({"cat": "pendant", "x": round(px, 3), "y": round(py, 3), "drop": 0.9})
    # a SECOND seating zone (S29F r4: 'seating clustered in the high-table zone, the rest of the hall vacant'): casual tables with two chairs each, spread through the back half between the high-table zone
    # and the elevator hall, leaving the LP-wall walkway (v > S - 3.4) and a 1.2 m aisle along the entrance wall open. Only in a hall long enough for the long-table layout.
    if long_ok:
        u = 9.6
        while u < L - 3.6:
            for v in (1.8 + 0.0, 1.8 + 2.7, 1.8 + 5.4):
                if v > S - 3.9:
                    continue
                x, y = world(u + rng.uniform(-0.25, 0.25), v + rng.uniform(-0.2, 0.2))
                if not far_free(x, y):
                    continue
                items.append({"cat": "casual_table", "x": round(x, 3), "y": round(y, 3), "yaw": 0.0})
                for dv in (-0.62, 0.62):
                    sx, sy = world(u, v + dv)
                    items.append({"cat": "casual_chair", "x": round(sx, 3), "y": round(sy, 3), "yaw": round(yaw_of(0, 1 if dv < 0 else -1), 4)})
            u += 3.2
    return {"items": items, "hung": hung}


if __name__ == "__main__":
    import collections
    p = layout(0, 14, 0, 9, 1, doors=[(0.0, 4.5)])
    print(dict(collections.Counter(e["cat"] for e in p["items"])), "hung", len(p["hung"]))
