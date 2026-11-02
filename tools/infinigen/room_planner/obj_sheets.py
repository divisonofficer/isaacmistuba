"""Labelled three-quarter contact sheets of data/object_library_v2: one PNG per category in sheets/. Builds index.json first (all .json sidecars).
    python obj_sheets.py [ROOT] [COLS] [CATEGORY...]     # infinigen python; Cycles CPU, neutral light"""
import sys, json, os, math, glob
import bpy
root = sys.argv[1] if len(sys.argv) > 1 else "/jarvis/project/robomituba/data/object_library_v2"; cols = int(sys.argv[2]) if len(sys.argv) > 2 else 8; only = sys.argv[3:]
idx = []
for f in sorted(glob.glob(f"{root}/*/*.json")):
    m = json.load(open(f)); m["file"] = os.path.relpath(f[:-5] + ".blend", root); idx.append(m)
json.dump(idx, open(f"{root}/index.json", "w"), indent=1)
os.makedirs(f"{root}/sheets", exist_ok=True)
cats = sorted({m["category"] for m in idx})
for cat in cats:
    if only and cat not in only:
        continue
    ms = [m for m in idx if m["category"] == cat and not m.get("skip")]
    bpy.ops.wm.read_factory_settings(use_empty=True); sc = bpy.context.scene
    cell = 1.6; rows = math.ceil(len(ms) / cols)
    tm = bpy.data.materials.new("tm"); tm.use_nodes = True; tm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.02, 0.02, 0.02, 1)
    for k, m in enumerate(ms):
        with bpy.data.libraries.load(os.path.join(root, m["file"]), link=False) as (a, b):
            b.objects = [n for n in a.objects if n == "ir_obj"]
        o = b.objects[0]; sc.collection.objects.link(o)
        dm = max(m["size"]) or 1e-3; k_ = 1.1 / dm; o.scale = (k_, k_, k_); o.rotation_euler[2] = math.radians(35)
        cx, cy = (k % cols) * cell, -(k // cols) * cell * 1.35
        o.location = (cx, cy, 0)
        t = bpy.data.objects.new("t", bpy.data.curves.new("t", "FONT")); t.data.body = f'{m["species"]} s{m["seed"]}\n{max(m["size"]) * 100:.0f} cm'; t.data.size = 0.11; t.data.align_x = "CENTER"
        sc.collection.objects.link(t); t.location = (cx, cy - 0.55, 0.001); t.data.materials.append(tm)
    import bmesh
    g = bpy.data.objects.new("g", bpy.data.meshes.new("g")); sc.collection.objects.link(g); bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=cell * (cols + 3)); bm.to_mesh(g.data)
    g.location = ((cols - 1) * cell / 2, -(rows - 1) * cell / 2, -0.001); gm = bpy.data.materials.new("gm"); gm.use_nodes = True; gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.8, 0.8, 0.8, 1); g.data.materials.append(gm)
    w = bpy.data.worlds.new("w"); w.use_nodes = True; w.node_tree.nodes["Background"].inputs[0].default_value = (0.9, 0.92, 0.95, 1); sc.world = w
    sun = bpy.data.lights.new("s", "SUN"); sun.energy = 3; so = bpy.data.objects.new("s", sun); sc.collection.objects.link(so); so.rotation_euler = (0.9, 0.2, 0.7)
    cam = bpy.data.objects.new("c", bpy.data.cameras.new("c")); sc.collection.objects.link(cam); sc.camera = cam; cam.data.type = "ORTHO"; cam.data.clip_end = 300
    ang = math.radians(50); tgt = ((cols - 1) * cell / 2, -(rows - 1) * cell * 0.675 - 0.1, 0.3)
    cam.location = (tgt[0], tgt[1] - math.cos(ang) * 40, tgt[2] + math.sin(ang) * 40); cam.rotation_euler = (math.pi / 2 - ang, 0, 0)
    cam.data.ortho_scale = cols * cell * 1.02
    sc.render.engine = "CYCLES"; sc.cycles.samples = 24; sc.cycles.use_denoising = False; sc.cycles.device = "CPU"
    sc.render.resolution_x = 2000; sc.render.resolution_y = int(2000 * (rows * cell * 1.35 * math.sin(ang) + 0.8) / (cols * cell) * 1.04); sc.render.filepath = f"{root}/sheets/{cat}.png"
    bpy.ops.render.render(write_still=True); print("SHEET", cat, len(ms), flush=True)
