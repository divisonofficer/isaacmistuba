import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r108_draft.blend';bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
for o in bpy.context.scene.objects:
 if o.type!='MESH':continue
 key=str(o.get('program_key',''));name=o.name
 if not any(t in (key+' '+name).lower() for t in ['night','bedside','lamp','bedroom','master']):continue
 pts=[o.matrix_world@Vector(v) for v in o.bound_box];lo=[min(v[k] for v in pts) for k in range(3)];hi=[max(v[k] for v in pts) for k in range(3)];rows.append({'object':name,'key':key,'parent':o.parent.name if o.parent else None,'children':[x.name for x in o.children],'min':lo,'max':hi,'polygons':len(o.data.polygons)})
(d/'bedroom110_current_inventory.json').write_text(json.dumps({'source':str(src),'sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'objects':rows,'scope':'Name/metadata-positive furniture inventory; not exhaustive semantic segmentation.'},indent=2));print(json.dumps(rows[:16],indent=2))
