"""Read-only material islands and bounds for workstation plant replacement."""
import bpy,json
from pathlib import Path
from collections import defaultdict
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r112_draft.blend';bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
for o in bpy.context.scene.objects:
 if o.type!='MESH':continue
 key=str(o.get('program_key',''))
 if not key.startswith('pod_') or '_chair' in key:continue
 groups=defaultdict(set)
 for f in o.data.polygons:groups[f.material_index].update(f.vertices)
 mats=[]
 for i,ids in groups.items():
  pts=[o.matrix_world@o.data.vertices[j].co for j in ids];lo=[min(v[k] for v in pts) for k in range(3)];hi=[max(v[k] for v in pts) for k in range(3)];m=o.data.materials[i] if i<len(o.data.materials) else None;mats.append({'index':i,'material':m.name if m else None,'world_min':lo,'world_max':hi,'vertices':len(ids)})
 rows.append({'object':o.name,'key':key,'materials':mats})
(d/'plants113_pod_materials.json').write_text(json.dumps(rows,indent=2));print(json.dumps(rows[:1],indent=2))
