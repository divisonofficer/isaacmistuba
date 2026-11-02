import bpy,json,statistics
from pathlib import Path
R=Path(__file__).resolve().parents[3]
for scene,seed,slot in [('rural_stone_cottage_04',48712504,'04'),('shared_dining_residence_05',48712505,'05')]:
 D=R/'data/venue_refs/floor_plans_v3'/scene;W=R/'out/infinigen_v2'/f'kr_{scene}_{seed}'/'full';src=W/f'scene_candidate_slots{slot}_r4.blend';out=W/f'scene_candidate_slots{slot}_r5.blend';assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(src));floors=[]
 for o in bpy.context.scene.objects:
  if o.type=='MESH' and o.name.endswith('.floor'):
   z=[(o.matrix_world@v.co).z for v in o.data.vertices];floors.append({'object':o.name,'min_z':min(z),'max_z':max(z)})
 floor=statistics.median([x['max_z'] for x in floors]);assert max(x['max_z'] for x in floors)-min(x['min_z'] for x in floors)<.001,floors
 products=[o for o in bpy.context.scene.objects if o.type=='MESH' and o.get('source_asset_id')];assert products
 before=min((o.matrix_world@v.co).z for o in products for v in o.data.vertices);assert abs(before-.025)<.001,before
 shift=floor-before;groups={}
 for o in products:
  key=o['source_asset_id'];groups.setdefault(key,[]).append(o);o.location.z+=shift
 bpy.context.view_layer.update();rows=[]
 for key,objects in groups.items():
  z=min((o.matrix_world@v.co).z for o in objects for v in o.data.vertices);rows.append({'source_asset_id':key,'objects':[o.name for o in objects],'minimum_world_z':z,'floor_support_delta_m':z-floor});assert abs(z-floor)<.001,(key,z,floor)
 bpy.ops.wm.save_as_mainfile(filepath=str(out));(D/'candidate_r5_support_audit.json').write_text(json.dumps({'source':str(src),'candidate':str(out),'floor_meshes':floors,'floor_reference_world_z':floor,'previous_product_base_z':before,'translation_z_m':shift,'native_product_groups':rows,'audit':'Native source dimensions and materials preserved; every source asset group baseline aligned to measured saved native floor. Each repeated instance was initially placed at identical baseline. No claim of collision/door sweep/plumbing completeness.','photorealism_accepted':False},indent=2));print('SUPPORT_R5_SAVED',scene,shift,flush=True)
