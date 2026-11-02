"""Remove measured obstructing stair ceiling, then assert tread headroom."""
import json
from pathlib import Path
import bpy
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3]
base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full'
ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r4.blend'))
room=json.loads((ref/'room_mapping.json').read_text())['stairs']['room_id']
ceiling=bpy.data.objects.get(room+'.ceiling')
assert ceiling,room
# Visibility flags do not remove physical collisions: remove the obsolete sheet.
bpy.data.objects.remove(ceiling,do_unlink=True)
bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();rays=[]
for o in bpy.data.objects:
    if o.get('audit_kind')!='stair_tread' or 'tread' not in o.get('program_key',''):continue
    pts=[o.matrix_world@Vector(c) for c in o.bound_box];center=sum(pts,Vector())/8;top=max(v.z for v in pts)
    hit,p,n,i,obj,m=bpy.context.scene.ray_cast(deps,Vector((center.x,center.y,top+.01)),Vector((0,0,1)),distance=6)
    clearance=p.z-top if hit else None
    rays.append({'tread':o.name,'clearance_m':clearance,'hit':obj.name if hit else None,'pass':clearance is None or clearance>=2})
result={'source':str(base/'scene_candidate_r5.blend'),'rays':rays,'all_pass':all(x['pass'] for x in rays),'scope':'vertical centre rays only; not swept-body certification'}
(ref/'stair_headroom_r5.json').write_text(json.dumps(result,indent=2))
assert result['all_pass'],result
bpy.ops.wm.save_as_mainfile(filepath=result['source'])
