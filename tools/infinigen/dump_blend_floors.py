"""Run inside Blender: dump the room floor meshes of a scene.blend without loading the rest of the file.

    blender --background --python blend_floors.py -- OUT.json
Reads only objects named <room>_<n>/<m>.floor (bpy.data.libraries.load), world-space vertices and polygon indices.
"""
import json, re, sys, time
import bpy  # type: ignore
t0 = time.time()
src = bpy.data.filepath if bpy.data.filepath else None
out = sys.argv[sys.argv.index("--") + 1]
blend = sys.argv[sys.argv.index("--") + 2]
pat = re.compile(r"^[a-z-]+_\d+/\d+\.floor$")
with bpy.data.libraries.load(blend, link=False) as (data_from, data_to):
    names = [n for n in data_from.objects if pat.match(n)]
    data_to.objects = names
rooms = {}
for ob in data_to.objects:
    if ob is None or ob.type != "MESH": continue
    mw = ob.matrix_basis      # not in any scene, so matrix_world was never evaluated; these floors have no parent
    verts = [list(mw @ v.co) for v in ob.data.vertices]
    rooms[ob.name.removesuffix(".floor")] = {"verts": verts, "faces": [list(p.vertices) for p in ob.data.polygons], "parent": ob.parent.name if ob.parent else None}
json.dump({"rooms": rooms, "n_names": len(names), "seconds": round(time.time() - t0, 1)}, open(out, "w"))
print("FLOORS", len(rooms), "rooms in", round(time.time() - t0, 1), "s")
