import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
r=Path('/jarvis/project/robomituba');s=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r60.blend';bpy.ops.wm.open_mainfile(filepath=str(s));bpy.context.view_layer.update();records=[]
for o in bpy.data.objects:
 if o.type!='MESH':continue
 key=str(o.get('program_key',''));name=o.name
 if not any(w in (name+' '+key).lower() for w in ['shower','elevator','kitchen','bath_mat']):continue
 pts=[o.matrix_world@Vector(v) for v in o.bound_box]
 records.append({'name':name,'key':key,'bounds':[[min(p[i] for p in pts) for i in range(3)],[max(p[i] for p in pts) for i in range(3)]],'matrix':[list(row) for row in o.matrix_world],'materials':[m.name if m else None for m in o.data.materials],'hidden_render':o.hide_render,'vertices':len(o.data.vertices)})
p=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/functional_probe_r60.json';p.write_text(json.dumps({'source':str(s),'source_sha256':hashlib.sha256(s.read_bytes()).hexdigest(),'objects':records},indent=2));print([(x['name'],x['key'],x['bounds']) for x in records])
