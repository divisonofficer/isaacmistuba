import bpy,json
from pathlib import Path
from mathutils import Vector
rows=[]
for o in bpy.data.objects:
 if o.type!='MESH':continue
 if o.get('ir_room') not in ('bathroom_0/4','bathroom_0/1','bathroom_0/5','garage_0/0','closet_0/0','utility_0/0','utility_0/1','kitchen_0/0') and not any(k in o.name for k in ('DoorFactory','Ficus','PivotGarden','PivotMatureTreeRig')):continue
 pts=[o.matrix_world@Vector(v) for v in o.bound_box]
 rows.append({'name':o.name,'room':o.get('ir_room'),'parent':o.parent.name if o.parent else None,'bounds':[[min(v[i] for v in pts),max(v[i] for v in pts)] for i in range(3)],'location':list(o.location),'rotation':list(o.rotation_euler),'materials':[m.name if m else None for m in o.data.materials]})
Path('/jarvis/project/robomituba/data/venue_refs/floor_plans_v3/pivot_courtyard_house_01/r10_object_inspection.json').write_text(json.dumps(rows,indent=2));print('INSPECT_R10_COMPLETE',flush=True)
