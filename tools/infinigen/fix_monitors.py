"""Turn every monitor / TV so its screen faces the person who uses it (user 2026-10-19: 'monitors are often turned around or rotated 90 degrees').

Late pass (kit_lighting.py calls apply(stats); ROOM_FIX_MONITORS=0 skips it). For each MonitorFactory / TVFactory mesh:
  screen direction = world-space normal of the faces the generator marks in its `screen` face attribute (tv.py), flattened to xy
  wanted direction = the staff side (-X) of the reception / pharmacy counter it stands on (those procedural counters have their visitor side at +X),
                     else toward the nearest chair / stool within 2 m, else away from the nearest wall within 1.2 m (a desk or TV stand against a wall faces the room)
  rotated about its own vertical axis when the two differ by more than 25 degrees. No chair and no wall: left alone (a counter monitor faces the staff side, not decidable here).
"""
import math

import bpy
from mathutils import Matrix, Vector

FACTORIES = ("MonitorFactory", "TVFactory")
SEATS = ("Chair", "Stool", "Sofa", "Bench")
COUNTERS = ("ReceptionDeskFactory", "PharmacyCounterFactory")      # front +X = the visitor side; the screen faces the staff, -X
TOL = math.radians(25)
SEAT_R, WALL_R = 2.0, 1.2


def _factory(o):
    return o.name.split("(")[0]


def screen_dir(o):
    attr = o.data.attributes.get("screen")
    if attr is None or attr.domain != "FACE":
        return None
    n = Vector((0, 0, 0))
    for p, v in zip(o.data.polygons, attr.data):
        if v.value:
            n += p.normal * p.area
    n = o.matrix_world.to_3x3() @ n
    n.z = 0
    return n.normalized() if n.length > 1e-4 else None        # a screen tilted flat is not a facing direction


def _centre(o):
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return Vector((sum(p.x for p in pts) / 8, sum(p.y for p in pts) / 8, min(p.z for p in pts))), pts


def counter_dir(o, counters):
    c = _centre(o)[0]
    for h in counters:
        pts = [h.matrix_world @ Vector(v) for v in h.bound_box]
        if min(p.x for p in pts) - 0.3 <= c.x <= max(p.x for p in pts) + 0.3 and min(p.y for p in pts) - 0.3 <= c.y <= max(p.y for p in pts) + 0.3:
            d = -(h.matrix_world.to_3x3() @ Vector((1, 0, 0)))
            d.z = 0
            if d.length > 1e-4:
                return d.normalized()
    return None


def wanted_dir(o, seats, depsgraph, scene, counters=()):
    c, pts = _centre(o)
    d0 = counter_dir(o, counters)
    if d0 is not None:
        return d0, "counter"
    best = None
    for s in seats:
        d = Vector((s.x - c.x, s.y - c.y, 0))
        if d.length < SEAT_R and (best is None or d.length < best.length):
            best = d
    if best is not None and best.length > 0.05:
        return best.normalized(), "seat"
    origin = Vector((c.x, c.y, c.z + 0.4)); near = None
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        hit = scene.ray_cast(depsgraph, origin, Vector((dx, dy, 0)), distance=WALL_R)
        if hit[0] and "wall" in hit[4].name.lower():
            dist = (hit[1] - origin).length
            if near is None or dist < near[0]:
                near = (dist, Vector((dx, dy, 0)))
    return (-near[1], "wall") if near else (None, "")


def apply(stats=None, dry=False):
    scene, deps = bpy.context.scene, bpy.context.evaluated_depsgraph_get()
    seats = []
    for o in bpy.data.objects:
        if o.type == "MESH" and o.parent is None and any(k in _factory(o) for k in SEATS):
            seats.append(_centre(o)[0])
    counters = [o for o in bpy.data.objects if o.type == "MESH" and _factory(o) in COUNTERS]
    done = []; n_mon = 0
    for o in list(bpy.data.objects):
        if o.type != "MESH" or _factory(o) not in FACTORIES:
            continue
        n_mon += 1
        cur = screen_dir(o)
        if cur is None:
            continue
        want, why = wanted_dir(o, seats, deps, scene, counters)
        if want is None:
            continue
        delta = math.atan2(cur.x * want.y - cur.y * want.x, cur.x * want.x + cur.y * want.y)
        if abs(delta) <= TOL:
            continue
        done.append((o.name, why, round(math.degrees(delta))))
        if dry:
            continue
        c = _centre(o)[0]
        pivot = Matrix.Translation(c)
        o.matrix_world = pivot @ Matrix.Rotation(delta, 4, "Z") @ pivot.inverted() @ o.matrix_world
        bpy.context.view_layer.update()
    if stats is not None:
        stats["monitors_turned"] = len(done); stats["monitors_seen"] = n_mon
    return done
