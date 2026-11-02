"""Inspect architectural visibility and shared fixtures before room relocation."""
import bpy,json
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];rows=[]
for o in bpy.data.objects:
 if o.type not in ('MESH','LIGHT','EMPTY'):continue
 pts=[o.matrix_world@Vector(v) for v in o.bound_box] if o.type=='MESH' else [o.matrix_world.translation]
 bounds=[[min(p[k] for p in pts),max(p[k] for p in pts)] for k in range(3)]
 x,y,z=bounds
 relevant=(x[1]>16.2 and x[0]<22.3 and y[1]>3.7 and y[0]<9.3) or (x[1]>23.5 and x[0]<26.7 and y[1]>14.2 and y[0]<17.3) or o.get('ir_room')=='kitchen_0/0'
 if not relevant:continue
 rows.append({'name':o.name,'type':o.type,'bounds':bounds,'parent':o.parent.name if o.parent else None,'room':str(o.get('ir_room','')),'hide_render':o.hide_render,'hide_viewport':o.hide_viewport,'visible':o.visible_get(),'modifiers':[{'name':m.name,'type':m.type,'render':m.show_render} for m in o.modifiers],'materials':[m.name if m else None for m in o.data.materials] if o.type=='MESH' else []})
p=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01/layout_connections_v2.json';p.write_text(json.dumps(rows,indent=2)+'\n');print('LAYOUT_CONNECTIONS_V2_READY',len(rows),flush=True)
