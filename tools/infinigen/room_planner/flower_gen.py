import sys, time
import bpy, numpy as np
sys.path[:0] = ["/root/module/infinigen"]
seed = int(sys.argv[1]); out = sys.argv[2]
from infinigen.assets.objects.grassland.flowerplant import FlowerPlantFactory
from infinigen.assets.utils.object import origin2lowest
t0 = time.time()
fac = FlowerPlantFactory(seed)
o = fac.spawn_asset(i=seed, loc=(0, 0, 0), rot=(0, 0, 0))
origin2lowest(o, approximate=True)
fac.finalize_assets(o)
bpy.ops.object.select_all(action="DESELECT")
objs = [x for x in [o] + list(o.children_recursive) if x.type == "MESH"]
for x in objs: x.select_set(True)
bpy.context.view_layer.objects.active = objs[0]
bpy.ops.object.join()
j = bpy.context.view_layer.objects.active
bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
co = np.array([v.co for v in j.data.vertices]); mn, mx = co.min(0), co.max(0)
j.data.transform(__import__("mathutils").Matrix.Translation((-(mn[0] + mx[0]) / 2, -(mn[1] + mx[1]) / 2, -mn[2])))
j.location = (0, 0, 0); j.name = "ir_plant"
print(f"FLOWER {seed} polys={len(j.data.polygons)} dims={(mx - mn).round(2)} mats={[m.name for m in j.data.materials]} secs={time.time() - t0:.0f}", flush=True)
bpy.data.libraries.write(f"{out}/flower_{seed:03d}.blend", {j}, compress=True)
