"""Read-only candidate plant assembly inventory before native library replacement."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r112_draft.blend';bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
for o in bpy.context.scene.objects:
 if o.type!='MESH':continue
 key=str(o.get('program_key',''));asset=str(o.get('original_asset_id',''));name=o.name
 if not any(t in (key+' '+asset+' '+name).lower() for t in ['plant','planter','foliage','succulent','tree','leaf','leaves','stem','flower','bush','decor','divider']):continue
 pts=[o.matrix_world@Vector(v) for v in o.bound_box];lo=[min(v[k] for v in pts) for k in range(3)];hi=[max(v[k] for v in pts) for k in range(3)];rows.append({'object':name,'program_key':key,'native_asset':asset,'parent':o.parent.name if o.parent else None,'children':[x.name for x in o.children],'world_min':lo,'world_max':hi,'vertices':len(o.data.vertices),'polygons':len(o.data.polygons),'materials':[m.name if m else None for m in o.data.materials]})
(d/'plants113_source_inventory.json').write_text(json.dumps({'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'objects':rows,'scope':'Name/metadata-positive plant inventory only. Not exhaustive semantic segmentation or placement acceptance.'},indent=2));print('PLANT_MESHES',len(rows))
