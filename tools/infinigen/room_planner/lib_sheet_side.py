"""Labelled SIDE-view contact sheet: models in a grid in the XZ plane (camera looks along +Y), species + seed + real height printed under each, drawn to a common display height.
    python lib_sheet_side.py INDEX.json OUT.png [COLS] [SKIPFILE]     # infinigen python"""
import sys, json, os, math
import bpy
from mathutils import Vector
idx = json.load(open(sys.argv[1])); outp = sys.argv[2]; cols = int(sys.argv[3]) if len(sys.argv) > 3 else 12
d = os.path.dirname(sys.argv[1]); skip = {m["file"] for m in idx if m.get("skip")}
idx = [m for m in idx if not m.get("skip")]
if len(sys.argv) > 5:                                                              # optional species filter (comma list): a sheet per group keeps memory under the 24 GB cap
    idx = [m for m in idx if m["species"] in sys.argv[5].split(",")]
bpy.ops.wm.read_factory_settings(use_empty=True); sc = bpy.context.scene
cell = 2.0; rows = math.ceil(len(idx) / cols)
tm = bpy.data.materials.new("tm"); tm.diffuse_color = (0, 0, 0, 1); tm.use_nodes = True; tm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.02, 0.02, 0.02, 1)
for k, m in enumerate(idx):
    with bpy.data.libraries.load(os.path.join(d, m["file"]), link=False) as (a, b):
        b.objects = [n for n in a.objects if n == "ir_plant"]
    o = b.objects[0]; sc.collection.objects.link(o)
    if len(o.data.polygons) > 40000:                                                             # the sheet only needs the silhouette: decimate for the render
        md = o.modifiers.new("dec", "DECIMATE"); md.ratio = 40000 / len(o.data.polygons)
        bpy.context.view_layer.objects.active = o; bpy.ops.object.modifier_apply(modifier=md.name)                  # apply now: the 800k-face original must not stay in memory for the whole sheet
    h = max(o.dimensions.z, 1e-3); k_ = 1.5 / max(h, o.dimensions.x * 0.8, o.dimensions.y * 0.8); o.scale = (k_, k_, k_)
    cx, cz = (k % cols) * cell, -(k // cols) * cell * 1.15
    o.location = (cx, 0, cz)
    t = bpy.data.objects.new("t", bpy.data.curves.new("t", "FONT")); t.data.body = f'{m["species"]} s{m["seed"]}\n{m["height"]:.2f} m'; t.data.size = 0.17; t.data.align_x = "CENTER"
    sc.collection.objects.link(t); t.rotation_euler = (math.pi / 2, 0, 0); t.location = (cx, -0.5, cz - 0.28); t.data.materials.append(tm)
w = bpy.data.worlds.new("w"); w.use_nodes = True; w.node_tree.nodes["Background"].inputs[0].default_value = (0.93, 0.94, 0.96, 1); sc.world = w
sun = bpy.data.lights.new("s", "SUN"); sun.energy = 3.5; so = bpy.data.objects.new("s", sun); sc.collection.objects.link(so); so.rotation_euler = (math.radians(55), 0, math.radians(20))
cam = bpy.data.objects.new("c", bpy.data.cameras.new("c")); sc.collection.objects.link(cam); sc.camera = cam
cam.data.type = "ORTHO"; W = cols * cell; Hh = rows * cell * 1.15
cam.location = ((cols - 1) * cell / 2, -30, -(rows - 1) * cell * 1.15 / 2 + 0.6); cam.rotation_euler = (math.pi / 2, 0, 0); cam.data.ortho_scale = W + 0.5; cam.data.clip_end = 100
sc.render.engine = "CYCLES"; sc.cycles.samples = 16; sc.cycles.use_denoising = False; sc.cycles.device = "CPU"
sc.render.resolution_x = 2400; sc.render.resolution_y = int(2400 * (Hh + 0.3) / (W + 0.5)); sc.render.filepath = outp
bpy.ops.render.render(write_still=True); print("SHEET", len(idx), outp)
