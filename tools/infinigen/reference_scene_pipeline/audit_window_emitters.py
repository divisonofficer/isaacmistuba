"""Read-only placement audit for scene-linked window child lights.

Bounds distance and near-normal direction only; no illumination or inward-side proof.
"""
import bpy,json,argparse,math
from pathlib import Path
from mathutils import Vector
p=argparse.ArgumentParser();p.add_argument('--blend',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
bpy.ops.wm.open_mainfile(filepath=str(a.blend))
# Hidden viewport objects retain stale cached matrix_world after reload.
# Evaluate them in memory only; this tool never saves the source.
for o in bpy.context.scene.objects:
 if o.type=='LIGHT' and o.parent and 'Window' in o.parent.name:o.hide_viewport=False
bpy.context.view_layer.update();rows=[];errors=[]
for light in bpy.context.scene.objects:
 if light.type!='LIGHT' or not light.parent or 'Window' not in light.parent.name:continue
 w=light.parent
 if w.type!='MESH':continue
 pts=[w.matrix_world@Vector(c) for c in w.bound_box]
 lo=Vector([min(v[i] for v in pts) for i in range(3)]);hi=Vector([max(v[i] for v in pts) for i in range(3)])
 pos=light.matrix_world.translation;distance=math.sqrt(sum(max(lo[i]-pos[i],0,pos[i]-hi[i])**2 for i in range(3)))
 extent=hi-lo;axis=min(range(3),key=lambda i:extent[i]);direction=(light.matrix_world.to_3x3()@Vector((0,0,-1))).normalized();cosine=abs(direction[axis])
 issues=[]
 if distance>.4:issues.append('light_more_than_400mm_from_window_bounds')
 if cosine<.8:issues.append('direction_not_near_glazing_normal')
 row={'object':light.name,'window':w.name,'world_location':list(pos),'distance_to_glazing_bounds_m':distance,'absolute_normal_alignment':cosine,'issues':issues};rows.append(row)
 if issues:errors.append(row)
a.out.write_text(json.dumps({'source':str(a.blend.resolve()),'scope':'Scene-linked window child light bounds-distance and direction only; no inward-side, occlusion, visibility or radiometric proof','lights':rows,'errors':errors,'error_count':len(errors),'photorealism_accepted':False},indent=2))
print(json.dumps({'lights':len(rows),'error_count':len(errors),'out':str(a.out)}),flush=True)
