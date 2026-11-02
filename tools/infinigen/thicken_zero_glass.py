"""Give every zero-thickness glass mesh a 6 mm closed slab (user 2026-10-26: "0 mm glass must not be made"). Mitsuba's dielectric (the polarised path has no thindielectric)
refracts a one-sided plane into a round fisheye; a closed slab refracts in and out and cancels it. The glass material is untouched.
  python thicken_zero_glass.py IN.blend OUT.blend [thickness_m]        (IN is never modified)
A mesh counts as glass when one of its materials is named *glass* or has Principled transmission >= 0.5 or a Glass BSDF; it is thickened when its smallest world bbox side is < 2 mm."""
import sys
import bpy, bmesh
from mathutils import Vector

IN, OUT = sys.argv[-3], sys.argv[-2]
try:
    T = float(sys.argv[-1])
    if T < 0.0005: raise ValueError
except ValueError:
    IN, OUT, T = sys.argv[-2], sys.argv[-1], 0.006
bpy.ops.wm.open_mainfile(filepath=IN)

def glassy(m):
    if m is None: return False
    if "glass" in m.name.lower(): return True
    if m.use_nodes:
        for n in m.node_tree.nodes:
            if n.type == "BSDF_GLASS": return True
            if n.type == "BSDF_PRINCIPLED":
                t = n.inputs.get("Transmission Weight") or n.inputs.get("Transmission")
                if t is not None and t.default_value >= 0.5: return True
    return False

done = {}
for o in list(bpy.data.objects):
    if o.type != "MESH" or not any(glassy(m) for m in o.data.materials): continue
    cs = [o.matrix_world @ Vector(c) for c in o.bound_box]
    if sorted(max(c[i] for c in cs) - min(c[i] for c in cs) for i in range(3))[0] >= 0.002: continue
    bm = bmesh.new(); bm.from_mesh(o.data); bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:]); bm.to_mesh(o.data); bm.free()
    md = o.modifiers.new("slab", "SOLIDIFY"); md.thickness = T; md.offset = 0.0; md.use_even_offset = True; md.use_rim = True
    bpy.context.view_layer.objects.active = o
    for ob in bpy.context.selected_objects: ob.select_set(False)
    o.select_set(True)
    try: bpy.ops.object.modifier_apply(modifier="slab")
    except RuntimeError as e:                                         # shared mesh data: make it single-user first
        bpy.ops.object.make_single_user(object=True, obdata=True); bpy.ops.object.modifier_apply(modifier="slab")
    key = o.name.split("(")[0]; done[key] = done.get(key, 0) + 1
bpy.ops.wm.save_as_mainfile(filepath=OUT)
print("SLAB", done, flush=True)
