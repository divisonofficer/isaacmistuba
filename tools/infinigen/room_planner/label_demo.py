"""Label-swap demo sheet: each product (rows) with 6 pack_atlas designs (columns), first column the original Infinigen label. -> data/object_library_v2/sheets/label_swap.png
    python label_demo.py [ROOT]     # infinigen python"""
import sys, os, math, json
import bpy
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import label_swap
root = sys.argv[1] if len(sys.argv) > 1 else "/jarvis/project/robomituba/data/object_library_v2"
idx = [m for m in json.load(open(f"{root}/index.json")) if m["category"] == "package" and any("shader_text" in (s["name"] or "") for s in m["slots"])]
pick = []
for sp in ("foodbox", "foodbag", "can", "bottle", "jar"):
    c = [m for m in idx if m["species"] == sp]
    pick += c[:1] + (c[3:4] if len(c) > 3 else [])
KS = [None, 3, 17, 42, 66, 88]
bpy.ops.wm.read_factory_settings(use_empty=True); sc = bpy.context.scene
cell = 0.5; rows = len(pick); cols = len(KS)
tm = bpy.data.materials.new("tm"); tm.use_nodes = True; tm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.02, 0.02, 0.02, 1)
for r_, m in enumerate(pick):
    for c_, k in enumerate(KS):
        with bpy.data.libraries.load(os.path.join(root, m["file"]), link=False) as (a, b):
            b.objects = ["ir_obj"]
        o = b.objects[0]; sc.collection.objects.link(o)
        kk = 0.38 / max(m["size"]); o.scale = (kk, kk, kk); o.rotation_euler[2] = math.radians(-30); o.location = (c_ * cell, -r_ * cell * 1.5, 0)
        if k is not None:
            label_swap.swap(o, k)
    t = bpy.data.objects.new("t", bpy.data.curves.new("t", "FONT")); t.data.body = f'{m["species"]} s{m["seed"]}'; t.data.size = 0.04; t.data.align_x = "RIGHT"
    sc.collection.objects.link(t); t.location = (-0.3, -r_ * cell * 1.5 - 0.02, 0.001); t.data.materials.append(tm)
import bmesh
g = bpy.data.objects.new("g", bpy.data.meshes.new("g")); sc.collection.objects.link(g); bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=12); bm.to_mesh(g.data); g.location = (1, -1, -0.001)
gm = bpy.data.materials.new("gm"); gm.use_nodes = True; gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.8, 0.8, 0.8, 1); g.data.materials.append(gm)
w = bpy.data.worlds.new("w"); w.use_nodes = True; w.node_tree.nodes["Background"].inputs[0].default_value = (0.9, 0.92, 0.95, 1); sc.world = w
sun = bpy.data.lights.new("s", "SUN"); sun.energy = 3; so = bpy.data.objects.new("s", sun); sc.collection.objects.link(so); so.rotation_euler = (0.9, 0.2, 0.7)
cam = bpy.data.objects.new("c", bpy.data.cameras.new("c")); sc.collection.objects.link(cam); sc.camera = cam; cam.data.type = "ORTHO"; cam.data.clip_end = 300
ang = math.radians(42); tgt = ((cols - 1) * cell / 2 - 0.1, -(rows - 1) * cell * 0.75, 0.15)
cam.location = (tgt[0], tgt[1] - math.cos(ang) * 40, tgt[2] + math.sin(ang) * 40); cam.rotation_euler = (math.pi / 2 - ang, 0, 0); cam.data.ortho_scale = (cols + 0.9) * cell
sc.render.engine = "CYCLES"; sc.cycles.samples = 48; sc.cycles.use_denoising = False; sc.cycles.device = "CPU"
sc.render.resolution_x = 1800; sc.render.resolution_y = int(1800 * (rows * cell * 1.5 * math.sin(ang) + 0.4) / ((cols + 0.9) * cell)); sc.render.filepath = f"{root}/sheets/label_swap.png"
bpy.ops.render.render(write_still=True); print("SHEET label_swap", len(pick))
