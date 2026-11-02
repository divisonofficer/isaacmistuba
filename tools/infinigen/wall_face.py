"""Inner wall faces for wall-mounted kit-stage pieces (shared by every shell; user 2026-10-25 F1 r5: walls ~0.1 m thick sit INSIDE the room's floor box, so pieces placed at box + 12 mm were buried).
inset(room, side) -> distance from the floor box edge to the wall's inner face (+3 mm), side in S / N / W / E; one ray per room side from the room centre at 1.2 m, cached per blend.
A ray that hits anything but the room's own wall (an opening, a fixture) falls back to 0.11 m. face(room, side) -> the face coordinate itself (y for S/N, x for W/E)."""
import bpy
from mathutils import Vector

FALLBACK = 0.0                                                # no wall found (glazing, an opening): pieces stay at the box edge, as before
_C = {}


def _bb(o):
    p = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return [min(q[i] for q in p) for i in range(3)], [max(q[i] for q in p) for i in range(3)]


def inset(room, side, fallback=None):
    key = (bpy.data.filepath, room, side, fallback)
    if key not in _C:
        d = FALLBACK if fallback is None else fallback; f = bpy.data.objects.get(f"{room}.floor")
        if f is not None:
            lo, hi = _bb(f)
            v, edge = {"S": (Vector((0, -1, 0)), lo[1]), "N": (Vector((0, 1, 0)), hi[1]), "W": (Vector((-1, 0, 0)), lo[0]), "E": (Vector((1, 0, 0)), hi[0])}[side]
            dg = bpy.context.evaluated_depsgraph_get(); hits = []
            for t in (0.5, 0.3, 0.7):                                   # three rays along the room; furniture / doors / shell pieces in the way are stepped through
                c = Vector((lo[0] + (hi[0] - lo[0]) * (t if v.y else 0.5), lo[1] + (hi[1] - lo[1]) * (0.5 if v.y else t), lo[2] + 1.2))
                for _ in range(40):
                    h, loc, _n, _i, o, _m = bpy.context.scene.ray_cast(dg, c, v)
                    if not h or o is None:
                        break
                    dd = abs((loc.y if v.y else loc.x) - edge)
                    if o.name.endswith(".wall") and dd < 0.35:           # this room's wall or the neighbour's (shared walls belong to one room); a hit far past the edge went through an opening
                        hits.append(dd); break
                    if ((loc.y if v.y else loc.x) - edge) * (v.y or v.x) > 0.35:     # already 0.35 m past the box edge: an opening / glazing, no wall on this side
                        break
                    c = loc + v * 0.002
            if hits:
                d = min(hits)
        _C[key] = d + 0.003
    return _C[key]


def face(room, side):
    lo, hi = _bb(bpy.data.objects[f"{room}.floor"])
    e = {"S": lo[1], "N": hi[1], "W": lo[0], "E": hi[0]}[side]
    return e + inset(room, side) * (1 if side in "SW" else -1)


def inner_box(room):
    """(lo, hi) of the room's floor box shrunk to its walls' inner faces (z untouched); (None, None) when the room has no floor."""
    f = bpy.data.objects.get(f"{room}.floor")
    if f is None:
        return None, None
    lo, hi = _bb(f)
    return [lo[0] + inset(room, "W"), lo[1] + inset(room, "S"), lo[2]], [hi[0] - inset(room, "E"), hi[1] - inset(room, "N"), hi[2]]
