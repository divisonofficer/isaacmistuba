import bpy,json
from pathlib import Path
r=Path('/jarvis/project/robomituba');bpy.ops.wm.open_mainfile(filepath=str(r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r62.blend'))
rows=[]
for o in bpy.data.objects:
 if o.type!='MESH' or 'chair' not in (o.name+' '+o.get('program_key','')).lower():continue
 rows.append({'name':o.name,'key':o.get('program_key'),'factory':o.get('infinigen_factory'),'vertices':len(o.data.vertices),'dimensions':list(o.dimensions),'materials':[m.name if m else None for m in o.data.materials]})
p=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/task_chair_inventory_r62.json';p.write_text(json.dumps(rows,indent=2));print(len(rows),flush=True)
