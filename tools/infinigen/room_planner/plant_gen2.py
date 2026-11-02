"""One Infinigen plant -> data/plant_library_v2/<species>_<seed>.blend (+ .json), joined mesh `ir_plant`, origin at base centre, +Z up, metres. One process per model (a segfault loses one model).
    python plant_gen2.py MODULE.Class SEED [OUT_DIR] [MAX_FACES]     # /root/miniconda3/envs/infinigen/bin/python
"""
import sys, time, json, importlib
import bpy, numpy as np
sys.path[:0] = ["/root/module/infinigen"]
spec, seed = sys.argv[1], int(sys.argv[2]); out = sys.argv[3] if len(sys.argv) > 3 else "/jarvis/project/robomituba/data/plant_library_v2"
maxf = int(sys.argv[4]) if len(sys.argv) > 4 else 150000
spec, _, kw = spec.partition(":")                                                  # "trees.TreeFactory:season=summer,fruit_chance=0"
kw = {k: (v if not v.replace(".", "").isdigit() else float(v)) for k, v in (p.split("=") for p in kw.split(",") if p)}
mod, cls = spec.rsplit(".", 1)
from infinigen.assets.utils.object import origin2lowest   # noqa: E402
fac = getattr(importlib.import_module("infinigen.assets.objects." + mod), cls)(seed, **kw)
t0 = time.time()
o = fac.spawn_asset(i=seed, loc=(0, 0, 0), rot=(0, 0, 0))
origin2lowest(o, approximate=True)
fac.finalize_assets(o)
def _realize_group():                                                                       # Geometry Nodes: Realize Instances (trees / palms keep their leaves as instances of a collection; convert() alone drops them)
    g = bpy.data.node_groups.new("ir_realize", "GeometryNodeTree")
    g.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"); g.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gi, go, rl = g.nodes.new("NodeGroupInput"), g.nodes.new("NodeGroupOutput"), g.nodes.new("GeometryNodeRealizeInstances")
    g.links.new(gi.outputs[0], rl.inputs[0]); g.links.new(rl.outputs[0], go.inputs[0])
    return g


bpy.ops.object.select_all(action="DESELECT")
objs = [x for x in [o] + list(o.children_recursive) if x.type in ("MESH", "CURVE")]
_rg = None
for x in objs:
    if any(md.type == "NODES" for md in x.modifiers):
        _rg = _rg or _realize_group(); md = x.modifiers.new("ir_realize", "NODES"); md.node_group = _rg
for x in objs:
    x.select_set(True)
bpy.context.view_layer.objects.active = objs[0]
bpy.ops.object.convert(target="MESH")                                                    # bake geometry-node / curve modifiers into real meshes (palms, coconut keep their geometry there)
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
j.location = (0, 0, 0); j.name = "ir_plant"
d = mx - mn; sp = cls.replace("Factory", "").lower() + ("_" + kw["season"] if "season" in kw else "")
meta = dict(species=sp, factory=spec, seed=seed, height=round(float(d[2]), 3), radius=round(float(max(d[0], d[1]) / 2), 3), faces=len(j.data.polygons), faces_orig=n0, has_pot=False,
            secs=round(time.time() - t0))
print("PLANT", json.dumps(meta), flush=True)
bpy.data.libraries.write(f"{out}/{sp}_{seed:03d}.blend", {j}, compress=True)
json.dump(meta, open(f"{out}/{sp}_{seed:03d}.json", "w"))
