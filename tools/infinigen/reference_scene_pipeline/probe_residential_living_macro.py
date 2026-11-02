"""Read actual retained residential source; report bounded living furniture/layout/fixture evidence."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];src=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r73.blend';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';before=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));bpy.context.view_layer.update();rows=[]
for o in bpy.context.scene.objects:
 key=o.get('program_key','')
 if not (key.startswith('101_') and any(s in key for s in ['living','sofa','rug','curtain','light','cove','coffee','table'])):continue
 pts=[o.matrix_world@Vector(p) for p in o.bound_box] if o.type in ['MESH','CURVE'] else [o.matrix_world.translation]
 rows.append({'name':o.name,'type':o.type,'program_key':key,'parent':o.parent.name if o.parent else None,'matrix_world':[list(r) for r in o.matrix_world],'world_bounds':[list(map(min,zip(*pts))),list(map(max,zip(*pts)))],'materials':[s.material.name if s.material else None for s in o.material_slots],'vertices':len(o.data.vertices) if o.type=='MESH' else None})
assert hashlib.sha256(src.read_bytes()).hexdigest()==before
(ref/'living_macro_source_r73_probe.json').write_text(json.dumps({'source':str(src),'source_sha256':before,'source_unchanged':True,'scope':'101 living-related program keys; bounding boxes only, not collision/contact certification','objects':rows},indent=2)+'\n');print('LIVING_MACRO_SOURCE_PROBE_COMPLETE',len(rows),flush=True)
