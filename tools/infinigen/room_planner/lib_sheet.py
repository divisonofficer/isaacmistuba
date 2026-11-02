"""Contact sheet of a model library: every <dir>/*.blend (object `ir_plant` or `ir_obj`) in a grid, Cycles, neutral light, label under each. Run with the infinigen python.
    python lib_sheet.py DIR OUT.png [GLOB] [COLS]"""
import sys, glob, os, json, math
import bpy
from mathutils import Vector
d, outp = sys.argv[1], sys.argv[2]; pat = sys.argv[3] if len(sys.argv) > 3 else "*.blend"; cols = int(sys.argv[4]) if len(sys.argv) > 4 else 6
files = sorted(glob.glob(os.path.join(d, pat)))
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene; objs = []
cell = 0.0
for f in files:
    with bpy.data.libraries.load(f, link=False) as (a, b):
        b.objects = [n for n in a.objects if n in ("ir_plant", "ir_obj")]
    for o in b.objects:
        hh = o.dimensions.z; o.name = "%s %.2fm" % (os.path.basename(f)[:-6], hh); sc.collection.objects.link(o); objs.append(o)
        k_ = 1.4 / max(hh, max(o.dimensions.x, o.dimensions.y) * 0.6, 1e-3); o.scale = (k_, k_, k_)          # every model drawn at a similar size; the label carries the real height
        cell = 1.6
cell = cell * 1.15 or 1.0; rows = math.ceil(len(objs) / cols)
for k, o in enumerate(objs):
    o.location = ((k % cols) * cell, -(k // cols) * cell, 0)
    t = bpy.data.objects.new("t", bpy.data.curves.new("t", "FONT")); t.data.body = o.name.replace("factory", ""); t.data.size = cell * 0.07
    sc.collection.objects.link(t); t.location = (o.location.x - cell * 0.4, o.location.y - cell * 0.3, 0.001)
    t.data.materials.append(bpy.data.materials.new("tm"))
cx, cy = (cols - 1) * cell / 2, -(rows - 1) * cell / 2
gnd = bpy.data.objects.new("g", bpy.data.meshes.new("g")); sc.collection.objects.link(gnd)
import bmesh; bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=cell * (cols + 2)); bm.to_mesh(gnd.data); gnd.location = (cx, cy, -0.002)
gm = bpy.data.materials.new("gm"); gm.diffuse_color = (0.8, 0.8, 0.8, 1); gm.use_nodes = True; gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.75, 0.75, 0.75, 1); gnd.data.materials.append(gm)
w = bpy.data.worlds.new("w"); w.use_nodes = True; w.node_tree.nodes["Background"].inputs[0].default_value = (0.85, 0.87, 0.9, 1); w.node_tree.nodes["Background"].inputs[1].default_value = 1.0; sc.world = w
sun = bpy.data.lights.new("s", "SUN"); sun.energy = 3; so = bpy.data.objects.new("s", sun); sc.collection.objects.link(so); so.rotation_euler = (0.8, 0.3, 0.6)
cam = bpy.data.objects.new("c", bpy.data.cameras.new("c")); sc.collection.objects.link(cam); sc.camera = cam
cam.data.type = "ORTHO"; ang = math.radians(60)
tgt = Vector((cx, cy, 0.5)); cam.location = tgt + Vector((0, -math.cos(ang), math.sin(ang))) * 40; cam.rotation_euler = (math.pi / 2 - ang, 0, 0)
cam.data.clip_end = 200; cam.data.ortho_scale = cols * cell * 1.02
asp = (rows * cell * math.sin(ang) + 1.6 * math.cos(ang)) / (cols * cell)
sc.render.engine = "CYCLES"; sc.cycles.samples = 16; sc.cycles.use_denoising = False; sc.cycles.device = "CPU"
sc.render.resolution_x = 2000; sc.render.resolution_y = int(2000 * asp * 1.04); sc.render.filepath = outp
bpy.ops.render.render(write_still=True); print("SHEET", len(objs), outp)
