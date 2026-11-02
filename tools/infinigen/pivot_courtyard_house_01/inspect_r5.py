import bpy,json
from pathlib import Path
from mathutils import Vector
rows=[]
for o in bpy.data.objects:
 if o.type!='MESH':continue
 if not (any(k in o.name for k in ('BedFactory','Pillow','Blanket','Comforter','Window','Blind','Monitor','TV','Sofa','Dining','KitchenIsland')) or o.get('ir_room')=='office_0/0'):continue
 pts=[o.matrix_world@Vector(v) for v in o.bound_box]
 rows.append({'name':o.name,'room':o.get('ir_room'),'parent':o.parent.name if o.parent else None,'bounds':[[min(v[i] for v in pts),max(v[i] for v in pts)] for i in range(3)],'materials':[m.name if m else None for m in o.data.materials]})
p=Path('/jarvis/project/robomituba/data/venue_refs/floor_plans_v3/pivot_courtyard_house_01/r5_object_inspection.json');p.write_text(json.dumps(rows,indent=2));print('INSPECTION',len(rows),flush=True)
