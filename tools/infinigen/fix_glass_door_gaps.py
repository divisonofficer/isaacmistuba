"""Cut the door openings out of BigGlass panes and frames in a finished blend (user 2026-10-26: a zero-thickness glass plane across a door opening blocks it; Mitsuba's dielectric then refracts it into a round fisheye).
  blender -b IN.blend --python fix_glass_door_gaps.py -- OUT.blend        (or: python fix_glass_door_gaps.py IN.blend OUT.blend with bpy installed)
Panes: split at the casing's inner edges (casing bbox minus 6 cm each side) and the faces inside are deleted. Frame: mullions inside the gap go, the sill rail is cut and its ends capped, the head rail above the door stays.
The input is never modified; the result is written to OUT.blend."""
import sys
import bpy, bmesh
from mathutils import Vector

IN, OUT = sys.argv[-2], sys.argv[-1]
bpy.ops.wm.open_mainfile(filepath=IN)

def wb(o):
    cs = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return Vector((min(c.x for c in cs), min(c.y for c in cs), min(c.z for c in cs))), Vector((max(c.x for c in cs), max(c.y for c in cs), max(c.z for c in cs)))

cas = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("DoorCasingFactory")]
stats = {"panes": 0, "frames": 0, "gaps": 0}

def gaps_for(lo, hi):
    ax = 0 if (hi.x - lo.x) > (hi.y - lo.y) else 1           # u axis = the long horizontal side of the glass run
    pl = (lo[1 - ax] + hi[1 - ax]) / 2; out = []
    for c in cas:
        cl, ch = wb(c)
        if abs((cl[1 - ax] + ch[1 - ax]) / 2 - pl) > 0.45: continue
        g0, g1 = cl[ax] + 0.06, ch[ax] - 0.06
        if g1 > lo[ax] - 0.1 and g0 < hi[ax] + 0.1 and g1 - g0 > 0.5: out.append((g0, g1, ch.z))
    return ax, sorted(out)

def cut(o, is_frame):
    lo, hi = wb(o); ax, gaps = gaps_for(lo, hi)
    if not gaps: return
    me = o.data; bm = bmesh.new(); bm.from_mesh(me); mw = o.matrix_world; mi = mw.inverted()
    n = Vector((1, 0, 0)) if ax == 0 else Vector((0, 1, 0))
    for g0, g1, ztop in gaps:
        for g in (g0, g1):
            co = Vector((g, 0, 0)) if ax == 0 else Vector((0, g, 0))
            bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=mi @ co, plane_no=mi.to_3x3() @ n)
        kill = []
        for f in bm.faces:
            c = mw @ f.calc_center_median()
            if g0 + 1e-4 < c[ax] < g1 - 1e-4 and (not is_frame or c.z < ztop - 0.2): kill.append(f)
        bmesh.ops.delete(bm, geom=kill, context="FACES")
        stats["gaps"] += 1
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    if is_frame:
        bnd = [e for e in bm.edges if len(e.link_faces) == 1]
        if bnd: bmesh.ops.holes_fill(bm, edges=bnd, sides=4)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(me); bm.free(); me.update(); stats["frames" if is_frame else "panes"] += 1

for o in list(bpy.data.objects):
    if o.type != "MESH": continue
    if o.name.startswith("BigGlassPanes"): cut(o, False)
    elif o.name.startswith("BigGlassFrame"): cut(o, True)
bpy.ops.wm.save_as_mainfile(filepath=OUT)
print("DOORGAPS", stats, flush=True)
