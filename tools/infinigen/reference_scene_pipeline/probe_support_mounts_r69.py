"""Read actual shelf/bracket and utility-wall bounds before manufacture/support refinement."""
import bpy,json
from pathlib import Path
from mathutils import Vector
r=Path('/jarvis/project/robomituba');bpy.ops.wm.open_mainfile(filepath=str(r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r69.blend'));bpy.context.view_layer.update();rows=[]
for o in bpy.data.objects:
 key=o.get('program_key','')
 if o.type!='MESH' or not (key in ['west_wall_shelf','east_wall_shelf','west_shelf_bracket','east_shelf_bracket'] or o.name.startswith(('utility_0/0','utility_0/1'))):continue
 pts=[o.matrix_world@Vector(c) for c in o.bound_box];rows.append({'name':o.name,'key':key,'bounds':[[min(p[k] for p in pts) for k in range(3)],[max(p[k] for p in pts) for k in range(3)]],'hide_render':o.hide_render})
p=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/support_mounts_probe_r69.json';p.write_text(json.dumps(rows,indent=2));print(p,len(rows),flush=True)
