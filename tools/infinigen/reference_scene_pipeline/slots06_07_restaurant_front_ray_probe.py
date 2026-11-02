import bpy,json
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];W=R/'out/infinigen_v2/kr_large_restaurant_floor_07_48712507';bpy.ops.wm.open_mainfile(filepath=str(W/'furnished_r12_calibrated.blend'));bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();rows=[]
for x in [6.2,7.6,8.8,9.2,10.8,12.3,14,16.5,18.7]:
 origin=Vector((x,14,1.65));hits=[]
 for j in range(12):
  ok,loc,norm,face,o,mat=bpy.context.scene.ray_cast(deps,origin,Vector((0,1,0)),distance=5)
  if not ok:break
  hits.append({'object':o.name,'position':list(loc),'normal':list(norm),'face':face,'materials':[m.name if m else None for m in o.data.materials],'hide_render':o.hide_render,'visible_camera':o.visible_camera});origin=loc+Vector((0,.003,0))
 rows.append({'x':x,'hits':hits})
(W/'black_front_actual_ray_probe_r12.json').write_text(json.dumps(rows,indent=2));print(json.dumps(rows,indent=2),flush=True)
