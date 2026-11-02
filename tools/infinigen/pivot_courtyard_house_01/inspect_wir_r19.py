import bpy,json,math
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full';B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';v=next(v for v in json.loads((F/'review_views_r19.json').read_text()) if v['name']=='wir_corridor_wide');loc=Vector(v['location']);rot=(Vector(v['target'])-loc).to_track_quat('-Z','Y');dg=bpy.context.evaluated_depsgraph_get();rows=[]
for x,y in [(720,510),(700,380),(660,250),(735,600),(650,410)]:
 ray=rot@Vector(((x/1024-.5)*2*math.tan(math.radians(v['hfov'])/2),(.5-y/768)*2*math.tan(math.radians(v['hfov'])/2)*.75,-1));hit,co,no,face,o,mat=bpy.context.scene.ray_cast(dg,loc,ray.normalized());rows.append({'pixel':[x,y],'hit':hit,'object':o.name if o else None,'face':face,'coordinate':list(co),'room':o.get('ir_room') if o else None})
(B/'wir_r19_ray_inspection.json').write_text(json.dumps(rows,indent=2));print('WIR_RAY_INSPECTION',json.dumps(rows),flush=True)
