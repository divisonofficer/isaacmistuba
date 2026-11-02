import bpy,json
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];S=R/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r105.blend';bpy.ops.wm.open_mainfile(filepath=str(S));rows=[]
for o in bpy.context.scene.objects:
 key=str(o.get('program_key',''))
 if not key.startswith('pod_') or o.type!='MESH':continue
 pts=[o.matrix_world@v.co for v in o.data.vertices];rows.append({'object':o.name,'key':key,'parent':o.parent.name if o.parent else None,'children':[c.name for c in o.children],'matrix':[list(v) for v in o.matrix_world],'bbox_m':[[min(p[k] for p in pts) for k in range(3)],[max(p[k] for p in pts) for k in range(3)]],'bbox_scope':'raw source mesh, not evaluated modifiers','vertices':len(o.data.vertices),'polygons':len(o.data.polygons),'seats':[list(seat) for seat in o.get('seats',[])],'materials':[m.name for m in o.data.materials if m]})
D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';(D/'usage108_source_inventory.json').write_text(json.dumps(rows,indent=2));print('USAGE108_INVENTORY',len(rows),flush=True)
