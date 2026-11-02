import bpy,json
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';rows=[]
for o in bpy.data.objects:
 if o.type!='MESH' or o.parent is not None or not o.visible_get():continue
 if o.name.endswith(('.floor','.wall','.ceiling','.meshed','.exterior')):continue
 pts=[o.matrix_world@Vector(v) for v in o.bound_box];bounds=[[min(v[k] for v in pts),max(v[k] for v in pts)] for k in range(3)];x,y,z=bounds
 if 'KitchenIslandFactory' in o.name or (x[1]>10.5 and x[0]<16.5 and y[1]>9 and y[0]<11.5):rows.append({'name':o.name,'room':str(o.get('ir_room','')),'bounds':bounds,'materials':[m.name if m else None for m in o.data.materials]})
(B/'family_layout_geometry_v18.json').write_text(json.dumps(rows,indent=2)+'\n');print('FAMILY_LAYOUT_GEOMETRY_READY',rows,flush=True)
