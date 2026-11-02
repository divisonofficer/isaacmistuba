"""Reference-plan placement helpers (user 2026-10-22: furniture placed from the floor plan; kit room_program[...]["layout"] = path to layout.json). Pure Python (no bpy), tested in __main__.

layout.json: {"items": [{"category", "u", "v", "facing": front|back|left|right|degrees, "against": front|back|left|right|null, "note"}]}, a normalised frame with the ENTRANCE wall at the bottom of the plan image:
u 0..1 left -> right along the entrance wall, v 0..1 entrance -> back wall; (u, v) = footprint centre. Degrees: 0 = front (toward the entrance), 90 = left, 180 = back, 270 = right (clockwise as seen in the plan).

    frame(walls, doors, poly)            -> (O, R, n, W, D, wall_id) or None: O = the left-hand end of the entrance wall (the wall carrying the widest door), R = unit vector to the right,
                                            n = inward normal, W = wall length along R, D = room depth along n
    to_world(fr, u, v)                   -> (x, y)
    direction(fr, facing)                -> (dx, dy) unit world vector of the item's front
    wall_for(walls, fr, side)            -> wall id whose inward normal best matches `side` ("front" = entrance wall ...)
All points are (x, y) tuples; `walls` = {id: ((ax, ay), (tx, ty), (nx, ny), length)}; doors = [{"wall", "width"}]; poly = [(x, y)].
"""
from __future__ import annotations

import json
import math


def load(path):
    return json.load(open(path)).get("items", [])


def meta(path):
    """The layout.json header without the items (entrance_u, plan_size_m, notes)."""
    d = json.load(open(path))
    return {k: v for k, v in d.items() if k != "items"}


def frame(walls, doors, poly):
    ds = [d for d in doors if d.get("wall") in walls]
    if not ds:
        return None
    dr = max(ds, key=lambda d: d.get("width", 0))
    (ax, ay), (tx, ty), (nx, ny), L = walls[dr["wall"]]
    R = (ny, -nx)                                                        # to the right when standing on the entrance wall looking into the room
    p0, p1 = (ax, ay), (ax + tx * L, ay + ty * L)
    dot = lambda p, q: p[0] * q[0] + p[1] * q[1]
    O = p0 if dot(p0, R) <= dot(p1, R) else p1
    W = abs(dot((p1[0] - p0[0], p1[1] - p0[1]), R))
    D = max(dot((x - O[0], y - O[1]), (nx, ny)) for x, y in poly)
    return O, R, (nx, ny), W, D, dr["wall"]


def to_world(fr, u, v):
    O, R, n, W, D, _ = fr
    return O[0] + R[0] * u * W + n[0] * v * D, O[1] + R[1] * u * W + n[1] * v * D


def direction(fr, facing):
    _, R, n, _, _, _ = fr
    if isinstance(facing, (int, float)):
        d = math.radians(facing)
    else:
        d = math.radians({"front": 0, "left": 90, "back": 180, "right": 270}.get(str(facing).lower(), 0))
    ix, iy = -math.sin(d), -math.cos(d)                                  # the plan image's (right, up) components of the front vector rotated clockwise by d
    return R[0] * ix + n[0] * iy, R[1] * ix + n[1] * iy


def wall_for(walls, fr, side):
    _, R, n, _, _, _ = fr
    want = {"front": n, "back": (-n[0], -n[1]), "left": R, "right": (-R[0], -R[1])}.get(side)
    if want is None:
        return None
    best = None
    for k, (_, _, nn, L) in walls.items():
        if nn[0] * want[0] + nn[1] * want[1] > 0.85 and (best is None or L > best[1]):
            best = (k, L)
    return best[0] if best else None


def door_u(fr, walls, doors):
    """Normalised u (0 = left end of the entrance wall) of the widest door on the entrance wall, or None."""
    O, R, n, W, D, wid = fr
    ds = [d for d in doors if d.get("wall") == wid]
    if not ds or W <= 0:
        return None
    dr = max(ds, key=lambda d: d.get("width", 0))
    (ax, ay), (tx, ty), _, L = walls[wid]
    px, py = ax + tx * dr["at_m"], ay + ty * dr["at_m"]
    return ((px - O[0]) * R[0] + (py - O[1]) * R[1]) / W


def mirror(items):
    """The plan seen in a mirror (the real door is on the other side of the entrance wall than the plan's entrance): u -> 1 - u, left <-> right, degrees -> 360 - d."""
    swap = {"left": "right", "right": "left"}
    out = []
    for e in items:
        f = e.get("facing", "front")
        f = (360 - f) % 360 if isinstance(f, (int, float)) else swap.get(str(f).lower(), f)
        ag = e.get("against")
        out.append({**e, "u": 1.0 - float(e["u"]), "facing": f, "against": swap.get(ag, ag) if isinstance(ag, str) else ag})
    return out


if __name__ == "__main__":
    # a 8.2 x 5.2 m room, door on the LONG bottom wall (y = 0), walls counter-clockwise: inward normals up / left / down / right
    walls = {"w1": ((0, 0), (1, 0), (0, 1), 8.2), "w2": ((8.2, 0), (0, 1), (-1, 0), 5.2), "w3": ((8.2, 5.2), (-1, 0), (0, -1), 8.2), "w0": ((0, 5.2), (0, -1), (1, 0), 5.2)}
    poly = [(0, 0), (8.2, 0), (8.2, 5.2), (0, 5.2)]
    fr = frame(walls, [{"wall": "w1", "width": 1.2}, {"wall": "w2", "width": 0.8}], poly)
    assert fr[5] == "w1" and abs(fr[3] - 8.2) < 1e-9 and abs(fr[4] - 5.2) < 1e-9, fr
    assert all(abs(a - b) < 1e-9 for a, b in zip(to_world(fr, 0.25, 0.5), (2.05, 2.6)))                  # u to the right, v into the room
    assert all(abs(a - b) < 1e-9 for a, b in zip(direction(fr, "front"), (0, -1))) and all(abs(a - b) < 1e-9 for a, b in zip(direction(fr, "left"), (-1, 0)))
    assert all(abs(a - b) < 1e-9 for a, b in zip(direction(fr, 270), (1, 0))) and all(abs(a - b) < 1e-9 for a, b in zip(direction(fr, "back"), (0, 1)))
    assert wall_for(walls, fr, "back") == "w3" and wall_for(walls, fr, "left") == "w0" and wall_for(walls, fr, "right") == "w2" and wall_for(walls, fr, "front") == "w1"
    # the same room entered from the right-hand short wall x = 8.2 (door on w2): the plan is rotated, u runs along the short wall
    fr2 = frame(walls, [{"wall": "w2", "width": 1.2}], poly)
    assert abs(fr2[3] - 5.2) < 1e-9 and abs(fr2[4] - 8.2) < 1e-9 and wall_for(walls, fr2, "back") == "w0"
    x, y = to_world(fr2, 0.0, 0.0); assert abs(x - 8.2) < 1e-9 and abs(y - 0.0) < 1e-9, (x, y)      # standing at x = 8.2 looking -x, the right hand points +y: u = 0 is the left-hand (y = 0) corner
    import tempfile, os
    _t = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False); json.dump({"entrance_u": 0.8, "items": []}, _t); _t.close()
    assert meta(_t.name)["entrance_u"] == 0.8 and "items" not in meta(_t.name); os.unlink(_t.name)
    du = door_u(fr, walls, [{"wall": "w1", "width": 1.2, "at_m": 2.0}]); assert abs(du - 2.0 / 8.2) < 1e-9, du
    m = mirror([{"u": 0.2, "v": 0.3, "facing": "left", "against": "right"}, {"u": 0.7, "v": 0.5, "facing": 90, "against": None}])
    assert m[0]["u"] == 0.8 and m[0]["facing"] == "right" and m[0]["against"] == "left" and m[1]["facing"] == 270, m
    print("layout_place OK", fr[:2], fr2[:2])
