"""Bounded saved-source appliance exterior audit; no navigation/door-opening certification."""
import bpy,bmesh,pathlib,json,hashlib
root=pathlib.Path('/jarvis/project/robomituba');src=root/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r66.blend';sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));bpy.context.view_layer.update();rows=[];errors=[]
for parent in [o for o in bpy.data.objects if o.type=='MESH' and 'HomeKitchenRunFactory' in o.name]:
 objs=[o for o in parent.children if o.name.startswith('Fridge66_')];assert len(objs)==10,(parent.name,len(objs));parts=[]
 for o in objs:
  bm=bmesh.new();bm.from_mesh(o.data);bad=sum(not e.is_manifold for e in bm.edges);volume=abs(bm.calc_volume());bm.free()
  if bad or volume<=0:errors.append({'object':o.name,'nonmanifold':bad,'volume':volume})
  bounds=[[min(v.co[k] for v in o.data.vertices),max(v.co[k] for v in o.data.vertices)] for k in range(3)];parts.append({'name':o.name,'nonmanifold_edges':bad,'volume_m3':volume,'local_bounds':bounds})
 doors=[x for x in parts if x['name'].startswith(('Fridge66_freezer_','Fridge66_fridge_'))];assert len(doors)==2;doors.sort(key=lambda p:p['local_bounds'][2][0]);gap=doors[1]['local_bounds'][2][0]-doors[0]['local_bounds'][2][1];assert abs(gap-.008)<1e-6
 body=next(x for x in parts if x['name'].startswith('Fridge66_body_'));assert abs(body['local_bounds'][2][0])<1e-7
 rows.append({'kitchen':parent.name,'parts':parts,'door_gap_m':gap,'body_bottom_matches_original_local_z':True,'handle_max_local_front_x':max(x['local_bounds'][0][1] for x in parts),'parent_transform':list(map(list,parent.matrix_world))})
assert len(rows)==2;assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;out={'source':str(src),'source_sha256':sha,'records':rows,'errors':errors,'scope':'Raw closed exterior meshes,door gap,original local bottom andpart count. Does not prove whole-scene collisions,physical support contact oropening clearance.','photorealism_accepted':False};(root/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/fridge_manufacture_audit_r66.json').write_text(json.dumps(out,indent=2));print(json.dumps({'records':len(rows),'errors':errors}));assert not errors
