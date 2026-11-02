import bpy,json
from pathlib import Path
R=Path(__file__).resolve().parents[3]
for scene,seed,slot,points in [('rural_stone_cottage_04',48712504,'04',[(6.7,5,2.25,300),(6.7,9,2.25,300),(1.7,9,2.25,100),(4.7,13.5,2.25,140),(12,5.5,2.25,120),(1.6,4.7,2.25,80),(8.3,13.5,2.25,60)]),('shared_dining_residence_05',48712505,'05',[(10,8.2,2.25,240),(10,5.3,2.25,200),(11.5,2,2.25,180),(3,8.5,2.25,150),(4,3.7,2.25,180),(2.25,1.5,2.25,35)])]:
 D=R/'data/venue_refs/floor_plans_v3'/scene;W=R/'out/infinigen_v2'/f'kr_{scene}_{seed}'/'full';src=W/f'scene_candidate_slots{slot}_r3.blend';out=W/f'scene_candidate_slots{slot}_r4.blend';assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
 for i,(x,y,z,power) in enumerate(points):
  l=bpy.data.lights.new(f'Interior_illumination_draft_{i}','AREA');l.energy=power;l.size=2.2;l.color=(1,.88,.72);o=bpy.data.objects.new(l.name,l);bpy.context.scene.collection.objects.link(o);o.location=(x,y,z);rows.append({'name':o.name,'location_m':[x,y,z],'power_W':power,'purpose':'temporary interior illumination below native ceiling; physical fixture not yet installed'})
 bpy.ops.wm.save_as_mainfile(filepath=str(out));(D/'candidate_r4_lighting.json').write_text(json.dumps({'candidate':str(out),'source':str(src),'lights':rows,'reason':'Rural r1 inspected room image underexposed: previous above-ceiling areas did not illuminate interior. Draft below-ceiling sources allow geometry/material review.','photorealism_accepted':False},indent=2))
