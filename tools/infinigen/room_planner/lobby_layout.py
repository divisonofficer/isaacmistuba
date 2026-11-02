"""Deterministic layout of the tall building lobby (S30, ROOM_MODE=lobby; refs out/room_planner_refs/lobby_tower_01). No bpy.

    layout(x0, x1, y0, y1, seed, obstacles=(), doors=()) -> {"items": [...], "hung": []}

Long axis u from the entrance end (the glass facade, u = 0): two revolving doors; a lounge zone of leather benches (2 rows x 3) in the middle; a glass cafe box against the far wall (centre) with
tables inside; three elevator doors on the left wall (v = 0) behind the benches; digital display walls along both long side walls from u = 12 to the cafe; a pixel-mosaic art panel by the far wall.
Wall pieces are `direct`; `lift` = mounting height. Needs a hall >= 18 x 12 m, smaller halls get fewer pieces.
"""
from __future__ import annotations

import math
import random

CATS = {"bench": "leather_bench", "display": "display_wall", "mosaic": "mosaic_panel", "revolve": "revolving_door", "cafe_box": "glass_cafe_box", "elevator": "elevator_door",
        "table": "cafe_table", "chair": "cafe_chair", "plant": "floor_plant"}
DROP = {"cafe_table", "cafe_chair", "bar_stool", "window_bar", "banquette_row", "banquette", "bookshelf", "bookcase", "sofa", "armchair", "reception_desk", "waiting_bench", "counter", "backbar_shelf",
        "coffee_table", "rug", "floor_plant", "break_table", "break_chair"}


def layout(x0, x1, y0, y1, seed=0, obstacles=(), doors=()):
    rng = random.Random(seed)
    W, D = x1 - x0, y1 - y0
    long_x = W >= D
    L, S = (W, D) if long_x else (D, W)
    world = (lambda u, v: (x0 + u, y0 + v)) if long_x else (lambda u, v: (x0 + v, y0 + u))
    yaw_of = lambda nu, nv: math.atan2(*((nv, nu) if long_x else (nu, nv)))
    items = []
    add = lambda cat, u, v, nu, nv, **kw: items.append({"cat": cat, "x": round(world(u, v)[0], 3), "y": round(world(u, v)[1], 3), "yaw": round(yaw_of(nu, nv), 4), **kw})
    for dv in (-2.3, 2.3):                                                              # revolving doors in the facade
        add("revolve", 1.6, S / 2 + dv, 1, 0, direct=True)
    ub = 0.38 * L                                                                       # the lounge zone: two rows of leather benches
    for k, du in enumerate((0.0, 3.0)):
        for dv in (-3.4, 0.0, 3.4):
            add("bench", ub + du, S / 2 + dv, 0, 1)
    if L >= 16 and S >= 10:
        add("cafe_box", L - 0.4 - 4.5, S / 2, 1, 0, direct=True)                                      # glass front toward the entrance, shelf wall at the far wall
        for dv in (-2.4, 0.0, 2.4):
            add("table", L - 2.4, S / 2 + dv, 1, 0, direct=True)
            for du, dvv in ((-0.65, 0.0), (0.65, 0.0)):
                add("chair", L - 2.4 + du, S / 2 + dv + dvv, 1 if du < 0 else -1, 0, direct=True)
        add("mosaic", L - 0.1, S * 0.2, -1, 0, direct=True, lift=0.3)
    for k in range(3):                                                                  # elevators behind the lounge, left wall
        add("elevator", 0.35 * L + 5.0 + k * 2.0, 0.04, 0, 1, direct=True)
    u = 0.33 * L
    while u + 5.0 <= L - 5.5:
        for v, nv in ((0.06, 1), (S - 0.06, -1)):
            add("display", u + 2.5, v, 0, nv, direct=True, lift=0.55)
        u += 5.2
    for u_, v_ in ((2.5, 1.2), (2.5, S - 1.2), (0.38 * L + 6.5, 1.0)):
        add("plant", u_, v_, 1, 0)
    return {"items": items, "hung": []}


if __name__ == "__main__":
    import collections
    p = layout(0, 30, 0, 18, 1)
    print(dict(collections.Counter(e["cat"] for e in p["items"])))
