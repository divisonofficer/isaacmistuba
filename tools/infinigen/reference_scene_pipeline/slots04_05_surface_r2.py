import bpy,json
from pathlib import Path
R=Path(__file__).resolve().parents[3]
for scene,seed,slot in [('rural_stone_cottage_04',48712504,'04'),('shared_dining_residence_05',48712505,'05')]:
 D=R/'data/venue_refs/floor_plans_v3'/scene;W=R/'out/infinigen_v2'/f'kr_{scene}_{seed}'/'full';src=W/f'scene_candidate_slots{slot}_r1.blend';out=W/f'scene_candidate_slots{slot}_r2.blend';assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(src));wood=next((m for m in bpy.data.materials if m.name=='shader_hardwood_floor'),None)
 if wood is None:
  # Native Infinigen wood material from unchanged cottage architecture, not image geometry.
  library=R/'out/infinigen_v2/kr_rural_stone_cottage_04_48712504/full/scene.blend'
  with bpy.data.libraries.load(str(library),link=False) as (a,b):b.materials=['shader_hardwood_floor']
  wood=b.materials[0]
 assert wood
 rows=[]
 for o in bpy.context.scene.objects:
  if o.type=='MESH' and o.name.endswith('.floor') and (slot=='04' or o.name.startswith(('living-room','bedroom'))):
   rows.append({'name':o.name,'before':[m.name for m in o.data.materials if m],'after':wood.name});o.data.materials.clear();o.data.materials.append(wood)
  if o.name.startswith('Cottage_structural_crossbeam'):o['reference_ceiling_detail']=True
 bpy.ops.wm.save_as_mainfile(filepath=str(out));(D/'candidate_r2_surface_changes.json').write_text(json.dumps({'source':str(src),'candidate':str(out),'changes':rows,'scope':'Native Infinigen hardwood material, source furniture UV and textures unchanged; no photorealism acceptance'},indent=2));print('SURFACE_R2_SAVED',scene)
