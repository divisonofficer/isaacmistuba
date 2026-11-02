"""Replace remaining private-office primitive chairs with already reviewed native product."""
import bpy,json,hashlib,math
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
root=Path(__file__).resolve().parents[3];base=root/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r108_draft.blend';out=base/'scene_candidate_r109_draft.blend';assert not out.exists();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();before=sha(src)
bpy.ops.wm.open_mainfile(filepath=str(src));scene=bpy.context.scene
proto=next(o for o in scene.objects if o.get('program_key')=='private_1_chair');assert proto.get('original_asset_id') and proto.type=='MESH';assert not proto.children
assert all(abs(x-1)<1e-6 for x in proto.scale)
def tree(o):
 ev=o.evaluated_get(bpy.context.evaluated_depsgraph_get());me=ev.to_mesh();pts=[o.matrix_world@v.co for v in me.vertices];t=BVHTree.FromPolygons(pts,[tuple(f.vertices) for f in me.polygons]);ev.to_mesh_clear();return t
rows=[]
for idx in range(2,7):
 key=f'private_{idx}_chair';old=next(o for o in scene.objects if o.get('program_key')==key);assert old.type=='MESH';props={k:old[k] for k in old.keys()};position=old.matrix_world.translation.copy();yaw=old.rotation_euler.z
 members={old}|set(old.children_recursive)|{o for o in scene.objects if str(o.get('program_key','')).startswith(key+'_')}
 # Native prototype has normalized local geometry; restore factory-facing convention.
 new=proto.copy();new.data=proto.data;scene.collection.objects.link(new);new.parent=None;new.name=f'NativeProductChair109_private{idx}'
 for k in list(new.keys()):del new[k]
 for k,v in props.items():new[k]=v
 new['original_asset_id']=proto['original_asset_id'];new['replacement_revision']=109;new.rotation_mode='XYZ';new.rotation_euler=(0,0,yaw+math.pi/2);new.scale=(1,1,1)
 floors=[o for o in scene.objects if o.type=='MESH' and o.name.endswith('.floor') and str(o.get('room_id',''))==str(old.get('room_id',''))]
 # Ray-test named architectural floor collection, never infer support from chair's old Z.
 if not floors:floors=[o for o in scene.objects if o.type=='MESH' and o.name.endswith('.floor')]
 hits=[]
 for floor in floors:
  hit=tree(floor).ray_cast(Vector((position.x,position.y,2)),Vector((0,0,-1)),3)[0]
  if hit is not None:hits.append(hit.z)
 assert hits,(key,'no floor support');floor_z=max(hits)
 local_lo=min(v.co.z for v in new.data.vertices);new.location=(position.x,position.y,floor_z-local_lo);bpy.context.view_layer.update()
 nt=tree(new);checks=[]
 for role in [f'private_{idx}_desk',f'private_{idx}_credenza']:
  obstacles=[o for o in scene.objects if o.type=='MESH' and o.get('program_key')==role];assert len(obstacles)==1
  pairs=nt.overlap(tree(obstacles[0]));checks.append({'role':role,'surface_intersections':len(pairs)});assert not pairs,(key,checks)
 removed=[o.name for o in members]
 for o in members:bpy.data.objects.remove(o,do_unlink=True)
 points=[new.matrix_world@v.co for v in new.data.vertices];lo=[min(v[k] for v in points) for k in range(3)];hi=[max(v[k] for v in points) for k in range(3)];assert abs(lo[2]-floor_z)<1e-5
 rows.append({'role':key,'removed':removed,'native_asset':new['original_asset_id'],'native_geometry_shared_with':proto.name,'bbox_min_m':lo,'bbox_max_m':hi,'scale':list(new.scale),'floor_gap_m':lo[2]-floor_z,'intersection_checks':checks})
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert sha(src)==before
(ref/'private_chairs109_build.json').write_text(json.dumps({'source':str(src),'source_sha256':before,'candidate':str(out),'candidate_sha256':sha(out),'replacements':rows,'scope':'Five native chair replacements. Bounded floor and static surface checks only; no full navigation or visual acceptance.','visual_accepted':False},indent=2));print('PRIVATE_CHAIRS109_SAVED')
