"""Corridor stub behind every door that opens onto nothing (S17 r34: the open door of a single-room scene looked straight into the empty world and rendered as a featureless pale panel).

    from door_backdrop import apply; stats["door_backdrop"] = apply()      # kit stage, only when ROOM_DOOR_BACKDROP=1

For each DoorCasingFactory whose outward side has no room / hallway floor within 0.6 m: a short lit corridor (floor, two side walls, end wall, ceiling, a warm ceiling strip), 1.7 m wide
and 1.8 m deep, starting at the wall's outer face. Env: ROOM_DOOR_BACKDROP_DEPTH (1.8), ROOM_DOOR_BACKDROP_W (1.7).
"""
from __future__ import annotations

import os

import bpy
from mathutils import Vector


def _bb(o):
    p = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return min(q.x for q in p), max(q.x for q in p), min(q.y for q in p), max(q.y for q in p), min(q.z for q in p), max(q.z for q in p)


def apply():
    from room_planner import proc_boutique_flagship as fl
    if os.environ.get("ROOM_DOOR_BACKDROP") != "1":
        return 0
    depth = float(os.environ.get("ROOM_DOOR_BACKDROP_DEPTH") or 1.8); W = float(os.environ.get("ROOM_DOOR_BACKDROP_W") or 1.7); H = 2.6; T = 0.06
    floors = [_bb(o) for o in bpy.data.objects if o.type == "MESH" and o.name.endswith(".floor")]

    def floor_at(x, y):
        return any(b[0] - 0.05 <= x <= b[1] + 0.05 and b[2] - 0.05 <= y <= b[3] + 0.05 for b in floors)
    wall = fl._flat("ir_dbd_wall", (0.82, 0.8, 0.76), 0.7); flo = fl._flat("ir_dbd_floor", (0.45, 0.44, 0.43), 0.5); ceil = fl._flat("ir_dbd_ceiling", (0.9, 0.9, 0.88), 0.8)
    led = fl._flat("ir_dbd_led", (1.0, 0.9, 0.72), 0.3); b = led.node_tree.nodes["Principled BSDF"]
    b.inputs["Emission Color"].default_value = (1.0, 0.9, 0.72, 1); b.inputs["Emission Strength"].default_value = 6.0
    n = 0
    for o in list(bpy.data.objects):
        if o.type != "MESH" or not o.name.startswith("DoorCasingFactory"):
            continue
        x0, x1, y0, y1, z0, _ = _bb(o); cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        along_x = (x1 - x0) > (y1 - y0)
        nrm = [Vector((0, 1, 0)), Vector((0, -1, 0))] if along_x else [Vector((1, 0, 0)), Vector((-1, 0, 0))]
        fl_ = [floor_at(cx + v.x * 0.6, cy + v.y * 0.6) for v in nrm]
        if fl_.count(True) != 1:                                  # inside to inside (two rooms) or no floor either side: not ours
            continue
        out = nrm[fl_.index(False)]                               # the side without a floor
        side = Vector((-out.y, out.x, 0))                         # along the wall
        base = Vector((cx, cy, z0)) + out * 0.12                  # the wall's outer face
        at = lambda a, d, z: (base.x + out.x * d + side.x * a, base.y + out.y * d + side.y * a, z0 + z)

        def box(a, d, z, sa, sd, sz):                             # a: along the wall, d: out from the wall
            x, y, zz = at(a, d, z)
            return ("box", x, y, zz, *((sd, sa) if abs(out.x) > 0.5 else (sa, sd)), sz)
        parts = [(flo, [box(0, depth / 2, -T / 2, W, depth, T)]),
                 (wall, [box(-W / 2 - T / 2, depth / 2, H / 2, T, depth, H), box(W / 2 + T / 2, depth / 2, H / 2, T, depth, H), box(0, depth + T / 2, H / 2, W + 2 * T, T, H)]),
                 (ceil, [box(0, depth / 2, H + T / 2, W + 2 * T, depth, T)]),
                 (led, [box(0, depth * 0.55, H - 0.01, 0.25, depth * 0.6, 0.012)])]
        fl.mesh_object(f"DoorBackdrop({o.name[-12:]})", parts, bevel=False)
        n += 1
    return n
