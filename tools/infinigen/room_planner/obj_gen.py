"""One Infinigen small object -> data/object_library_v2/<category>/<species>_<seed>.blend (+ .json): one joined mesh `ir_obj`, origin at the base centre, +Z up, metres, Infinigen's own materials.
    python obj_gen.py CATEGORY MODULE.Class SEED [OUT_ROOT] [MAX_FACES]     # /root/miniconda3/envs/infinigen/bin/python, one process per model"""
import sys, time, json, importlib, os
import bpy, numpy as np
sys.path[:0] = ["/root/module/infinigen"]
cat, spec, seed = sys.argv[1], sys.argv[2], int(sys.argv[3])
root = sys.argv[4] if len(sys.argv) > 4 else "/jarvis/project/robomituba/data/object_library_v2"; maxf = int(sys.argv[5]) if len(sys.argv) > 5 else 60000
mod, cls = spec.rsplit(".", 1)
fac = getattr(importlib.import_module("infinigen.assets.objects." + mod), cls)(seed)
t0 = time.time()
o = fac.spawn_asset(i=seed, loc=(0, 0, 0), rot=(0, 0, 0))
fac.finalize_assets(o)
bpy.ops.object.select_all(action="DESELECT")
objs = [x for x in [o] + list(o.children_recursive) if x.type in ("MESH", "CURVE")]
for x in objs:
    x.select_set(True)
bpy.context.view_layer.objects.active = objs[0]
bpy.ops.object.convert(target="MESH")
objs = [x for x in bpy.context.selected_objects if x.type == "MESH" and len(x.data.polygons)]
bpy.ops.object.select_all(action="DESELECT")
for x in objs:
    x.select_set(True)
bpy.context.view_layer.objects.active = objs[0]
bpy.ops.object.join()
j = bpy.context.view_layer.objects.active
bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
n0 = len(j.data.polygons)
if n0 > maxf:
    m = j.modifiers.new("dec", "DECIMATE"); m.ratio = maxf / n0
    bpy.ops.object.modifier_apply(modifier=m.name)
co = np.array([v.co for v in j.data.vertices]); mn, mx = co.min(0), co.max(0)
j.data.transform(__import__("mathutils").Matrix.Translation((-(mn[0] + mx[0]) / 2, -(mn[1] + mx[1]) / 2, -mn[2])))
j.location = (0, 0, 0); j.name = "ir_obj"
d = mx - mn; sp = cls.replace("Factory", "").replace("FruitFactory", "fruit_").lower()
slots = []
for k, ms in enumerate(j.material_slots):
    m_ = ms.material; img = False; nm = m_.name if m_ else None
    if m_ is not None and m_.use_nodes:
        img = any(n.type == "TEX_IMAGE" for n in m_.node_tree.nodes)
    slots.append({"slot": k, "name": nm, "faces": int(sum(1 for p in j.data.polygons if p.material_index == k)), "image_texture": img})
meta = dict(category=cat, species=sp, factory=spec, seed=seed, size=[round(float(v), 4) for v in d], height=round(float(d[2]), 4), faces=len(j.data.polygons), faces_orig=n0, slots=slots, label_slot=None, secs=round(time.time() - t0))
os.makedirs(f"{root}/{cat}", exist_ok=True)
print("OBJ", json.dumps(meta)[:300], flush=True)
bpy.data.libraries.write(f"{root}/{cat}/{sp}_{seed:03d}.blend", {j}, compress=True)
json.dump(meta, open(f"{root}/{cat}/{sp}_{seed:03d}.json", "w"))
