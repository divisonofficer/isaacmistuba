"""Build one Infinigen plant (banana / agave / veratrum / generic monocot by seed) offline and save it to data/plant_library/plant_<seed>.blend (single mesh object `ir_plant`,
origin at the stem base centre, +Z up, metres). The activity pass appends these instead of growing a plant per scene: a plant
takes 4-5 min and intermittently segfaults Blender (floors B, J, A2, 2026-10-16), so growing happens here, in its own process,
and a crash costs one retry.
    python plant_gen.py SEED [OUT_DIR]      # run with /root/miniconda3/envs/infinigen/bin/python
"""
import sys, time
import bpy, numpy as np
sys.path[:0] = ["/root/module/infinigen"]
seed = int(sys.argv[1]); out = sys.argv[2] if len(sys.argv) > 2 else "/jarvis/project/robomituba/data/plant_library"
from infinigen.assets.objects import monocot as M   # noqa: E402
from infinigen.assets.utils.object import origin2lowest   # noqa: E402
KINDS = [M.BananaMonocotFactory, M.AgaveMonocotFactory, M.VeratrumMonocotFactory, M.MonocotFactory]
t0 = time.time()
fac = KINDS[seed % len(KINDS)](seed)
o = fac.spawn_asset(i=seed, loc=(0, 0, 0), rot=(0, 0, 0))
origin2lowest(o, approximate=True)
fac.finalize_assets(o)
bpy.ops.object.select_all(action="DESELECT")
objs = [x for x in [o] + list(o.children_recursive) if x.type == "MESH"]   # not the placeholder bbox spawn_asset leaves in the scene
for x in objs:
    x.select_set(True)
bpy.context.view_layer.objects.active = objs[0]
bpy.ops.object.join()
j = bpy.context.view_layer.objects.active
bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
co = np.array([v.co for v in j.data.vertices]); mn, mx = co.min(0), co.max(0)
j.data.transform(__import__("mathutils").Matrix.Translation((-(mn[0] + mx[0]) / 2, -(mn[1] + mx[1]) / 2, -mn[2])))
j.location = (0, 0, 0); j.name = "ir_plant"
print(f"PLANT {seed} polys={len(j.data.polygons)} dims={(mx - mn).round(2)} secs={time.time() - t0:.0f}", flush=True)
bpy.data.libraries.write(f"{out}/plant_{seed:03d}.blend", {j}, compress=True)
