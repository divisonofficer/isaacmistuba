import bpy,json
from pathlib import Path
R=Path(__file__).resolve().parents[3];p=R/'out/infinigen_v2/kr_rural_stone_cottage_04_48712504/full/scene_candidate_slots04_r1.blend';bpy.ops.wm.open_mainfile(filepath=str(p));rows=[]
for o in bpy.context.scene.objects:
 if o.type=='MESH':
  rows.append({'name':o.name,'dims':list(o.dimensions),'location':list(o.location),'materials':[m.name for m in o.data.materials if m]})
(R/'data/venue_refs/floor_plans_v3/rural_stone_cottage_04/candidate_r1_objects.json').write_text(json.dumps(rows,indent=2))
