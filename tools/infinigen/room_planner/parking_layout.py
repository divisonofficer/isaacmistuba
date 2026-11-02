"""Deterministic layout of the underground parking level (S28, ROOM_MODE=parking; docs/parking_bldg_design_proposal.md). No bpy.

    layout(x0, x1, y0, y1, seed, obstacles=(), doors=()) -> {"items": [...], "hung": [...]}

Bands of 16 m across the short axis: a bay row (5.0 m deep) / a 6.0 m aisle / a bay row (5.0 m), bays 2.6 m wide, about 65 % of them holding a parked car (nose in or out at random). A square column with a
number plate stands on every third bay line at the aisle edge. White bay lines (flat, direct), floor arrows along each aisle, orange cones in the aisles, wheel stops in some bays, bollards beside a few
columns, green exit signs hung over the aisle ends. Doors are kept clear (2.5 m).
"""
from __future__ import annotations

import math
import os
import random

CATS = {"car": "parked_car", "column": "parking_column", "cone": "traffic_cone", "bollard": "bollard", "wheelstop": "wheel_stop", "bay_lines": "bay_lines", "arrow": "floor_arrow", "exit": "exit_sign"}
DROP = {"pallet_rack", "storage_rack", "workbench", "pallet", "utility_cart", "supply_shelf", "stock_shelf", "wide_shelf", "floor_plant", "small_plant", "cardboard_box", "counter"}
BAY_W, BAY_D, AISLE, BAND = 2.6, 5.0, 6.0, 16.0


def layout(x0, x1, y0, y1, seed=0, obstacles=(), doors=()):
    rng = random.Random(seed)
    W, D = x1 - x0, y1 - y0
    long_x = W >= D
    L, S = (W, D) if long_x else (D, W)
    world = (lambda u, v: (x0 + u, y0 + v)) if long_x else (lambda u, v: (x0 + v, y0 + u))
    yaw_of = lambda nu, nv: math.atan2(*((nv, nu) if long_x else (nu, nv)))
    near_door = lambda x, y, r=2.5: any(abs(x - dx) < r and abs(y - dy) < r for dx, dy in doors)
    items, hung = [], []
    n_bays = max(1, int((L - 1.0) // BAY_W)); u0 = (L - n_bays * BAY_W) / 2
    bands = max(1, int((S - 0.3) // BAND)) if S >= BAND else 1
    for b in range(bands):
        v0 = 0.25 + b * BAND
        rows = [(v0, 1)] + ([(v0 + BAND - 0.5 - BAY_D + 0.0, -1)] if S - v0 >= BAND - 0.5 else [])     # (back line v, +1 = faces +v)
        if S - v0 < BAY_D + AISLE:                                                                     # a short room: one row only
            rows = [(v0, 1)]
        for back_v, face in rows:
            FIX = os.environ.get("ROOM_PARKING_BAYFIX") == "1"                                    # S28F: the row that faces -v had its lines drawn from the near edge OUTWARDS (5 m off), the cars in the bay -> 'every car outside the lines'
            bl_v = (back_v + BAY_D) if (FIX and face < 0) else back_v                               # the back line of this row (the wall side)
            # bay lines: chunks of 6 bays, origin so the 'back line' runs along +u
            dy_uv = lambda nu, nv: (-nv, nu) if long_x else (nv, -nu)               # the object's +y direction in (u, v) for a front (+x) toward (nu, nv)
            nu, nv = 0, face
            ydir = dy_uv(nu, nv)
            k = 0
            while k < n_bays:
                m = min(6, n_bays - k)
                ustart, uend = u0 + k * BAY_W, u0 + (k + m) * BAY_W
                uo = ustart if ydir[0] > 0 else uend
                x, y = world(uo, bl_v)
                items.append({"cat": "bay_lines", "x": round(x, 3), "y": round(y, 3), "yaw": round(yaw_of(nu, nv), 4), "direct": True})
                k += m
            # cars
            for k in range(n_bays):
                uc = u0 + (k + 0.5) * BAY_W
                if rng.random() > 0.65:
                    if rng.random() < 0.25:
                        x, y = world(uc, bl_v + face * 0.35 if FIX else back_v + 0.35)
                        items.append({"cat": "wheelstop", "x": round(x, 3), "y": round(y, 3), "yaw": round(yaw_of(0, face), 4)})
                    continue
                nose_in = rng.random() < 0.55
                vc = (bl_v + face * 2.65 + rng.uniform(-0.05, 0.05)) if FIX else (back_v + 2.65 + rng.uniform(-0.12, 0.12))
                x, y = world(uc + rng.uniform(-0.05 if FIX else -0.1, 0.05 if FIX else 0.1), vc)
                if near_door(x, y):
                    continue
                items.append({"cat": "car", "x": round(x, 3), "y": round(y, 3), "yaw": round(yaw_of(0, -face if nose_in else face) + rng.uniform(-0.035, 0.035), 4)})
                if os.environ.get("ROOM_PARKING_FIXTURES") == "1":                       # a wheel stop in EVERY occupied bay (S28F fixtures ticket), 0.35 m from the wall-side line
                    wx, wy = world(uc, (bl_v + face * 0.55) if FIX else back_v + 0.55)
                    items.append({"cat": "wheelstop", "x": round(wx, 3), "y": round(wy, 3), "yaw": round(yaw_of(0, face), 4), "direct": True})      # flush: it sits under / beside the car's front tyres, no footprint test
            # columns on every third bay line at the aisle edge, plate facing the aisle
            for k in range(0, n_bays + 1, 3):
                uc = u0 + k * BAY_W
                x, y = world(uc, (bl_v + face * (BAY_D - 0.3)) if FIX else back_v + (BAY_D - 0.3))
                items.append({"cat": "column", "x": round(x, 3), "y": round(y, 3), "yaw": round(yaw_of(0, face), 4), "direct": True})     # S28 r6: 5 of 10 columns failed the footprint check (they stand between two bays)
        # aisle: arrows every 10 m, cones, an exit sign over each end
        av = v0 + BAY_D + AISLE / 2 if len(rows) > 1 or S - v0 >= BAY_D + AISLE else v0 + BAY_D + 1.0
        uu = u0 + 4.0
        while uu < L - 3.0:
            x, y = world(uu, av)
            items.append({"cat": "arrow", "x": round(x, 3), "y": round(y, 3), "yaw": round(yaw_of(1, 0) if (int(uu) // 10) % 2 == 0 else yaw_of(-1, 0), 4), "direct": True})
            uu += 7.0
        for _ in range(rng.randint(2, 4)):
            x, y = world(rng.uniform(3, L - 3), av + rng.uniform(-1.8, 1.8))
            if not near_door(x, y, 1.5):
                items.append({"cat": "cone", "x": round(x, 3), "y": round(y, 3), "yaw": round(rng.uniform(0, 6.28), 4)})
        # exit signs now hang from parking_ceiling.py (large double-sided signs over the aisle, every 16 m)
    return {"items": items, "hung": hung}


if __name__ == "__main__":
    import collections
    p = layout(0, 40, 0, 17, 1, doors=[(0.0, 8.0)])
    print(dict(collections.Counter(e["cat"] for e in p["items"])), "hung", len(p["hung"]))
