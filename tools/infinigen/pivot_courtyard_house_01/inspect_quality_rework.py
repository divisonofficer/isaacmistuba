import bpy,json,math
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full';rows=[]
for o in bpy.data.objects:
 if o.type!='MESH':continue
 room=str(o.get('ir_room',''));name=o.name.lower()
 relevant=room in ('utility_0/1','garage_0/0','living-room_0/2','hallway_0/0','kitchen_0/0','office_0/0') or any(k in name for k in ('courtyard','entrydeck','entry_deck')) or any(o.name.startswith(k) for k in ('living-room_0/2.','kitchen_0/0.','garage_0/0.','hallway_0/0.'))
 if not relevant:continue
 pts=[o.matrix_world@Vector(v) for v in o.bound_box];rows.append({'name':o.name,'room':room,'parent':o.parent.name if o.parent else None,'bounds':[[min(v[k] for v in pts),max(v[k] for v in pts)] for k in range(3)],'materials':[m.name if m else None for m in o.data.materials]})
v=next(x for x in json.loads((F/'review_views_r21.json').read_text()) if x['name']=='courtyard_reference_wide');loc=Vector(v['location']);q=(Vector(v['target'])-loc).to_track_quat('-Z','Y');dg=bpy.context.evaluated_depsgraph_get();rays=[]
for x,y in [(.15,.45),(.35,.45),(.55,.45),(.75,.45),(.90,.45),(.35,.7)]:
 ray=q@Vector(((x-.5)*2*math.tan(math.radians(v['hfov'])/2),(.5-y)*2*math.tan(math.radians(v['hfov'])/2)*.75,-1));hit,co,no,face,o,ma=bpy.context.scene.ray_cast(dg,loc,ray.normalized());rays.append({'pixel_normalized':[x,y],'hit':hit,'object':o.name if o else None,'point':list(co)})
(B/'quality_rework_geometry.json').write_text(json.dumps({'objects':rows,'courtyard_rays':rays},indent=2));print('QUALITY_REWORK_GEOMETRY_READY',len(rows),flush=True)
