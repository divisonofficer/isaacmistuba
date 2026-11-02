"""One actual product-chair room trial; preserves source79 lighting/layout and original PBR."""
import bpy,json,math,hashlib
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
root=Path(__file__).resolve().parents[3];base=root/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';assets=ref/'real_chair_candidates';src=base/'scene_candidate_r79.blend';out=base/'scene_candidate_r84.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();prototype=assets/'review_studio_textures_fixed.blend';proto_sha=hashlib.sha256(prototype.read_bytes()).hexdigest();scope=json.loads((assets/'review_scope.json').read_text());row=next(r for r in scope['assets'] if r['id']=='B06W5XBL3D');assert len(row['objects'])==1;bpy.ops.wm.open_mainfile(filepath=str(src));old=[o for o in bpy.data.objects if o.get('program_key')=='private_1_chair'];assert len(old)==1;old=old[0];assert not old.children;old_name=old.name;old_yaw=old.rotation_euler.z;old_xy=[old.location.x,old.location.y];props={k:old[k] for k in old.keys()};legacy_aux=[o for o in bpy.data.objects if str(o.get('program_key','')).startswith('private_1_chair_')];removed_aux=[{'name':o.name,'key':o.get('program_key')} for o in legacy_aux]
with bpy.data.libraries.load(str(prototype),link=False) as (a,b):b.objects=row['objects']
new=b.objects[0];assert new and new.type=='MESH';bpy.context.scene.collection.objects.link(new);bpy.context.view_layer.update();world=new.matrix_world.copy();new.data=new.data.copy();new.data.transform(world);new.parent=None;new.matrix_world=Matrix.Identity(4)
points=[v.co for v in new.data.vertices];lo=Vector(tuple(min(v[k] for v in points) for k in range(3)));hi=Vector(tuple(max(v[k] for v in points) for k in range(3)));new.data.transform(Matrix.Translation(Vector((-(lo.x+hi.x)/2,-(lo.y+hi.y)/2,-lo.z))))
assert .85<hi.z-lo.z<1.0,('actual product bounds afterlinked depsgraph update',list(lo),list(hi),[list(r) for r in world]);assert max(abs((hi-lo)[k]-row['original_world_extents_m'][k]) for k in range(3))<1e-5
floor=bpy.data.objects['office_0/0.floor'];ev=floor.evaluated_get(bpy.context.evaluated_depsgraph_get());me=ev.to_mesh();pts=[floor.matrix_world@v.co for v in me.vertices];tree=BVHTree.FromPolygons(pts,[tuple(f.vertices) for f in me.polygons]);top=max(v.z for v in pts);hit=tree.ray_cast(Vector((*old_xy,top+.5)),Vector((0,0,-1)),2)[0];ev.to_mesh_clear();assert hit is not None
new.rotation_mode='XYZ';new.rotation_euler=(0,0,old_yaw+math.pi/2);new.location=(*old_xy,hit.z);bpy.context.view_layer.update();points=[new.matrix_world@v.co for v in new.data.vertices];assert abs(min(v.z for v in points)-hit.z)<1e-5
expected={(r['png_sha256'],r['colorspace']) for r in json.loads((assets/'embedded_texture_repair.json').read_text())['repairs'] if r['asset_id']=='B06W5XBL3D'};actual=set()
for slot in new.material_slots:
 assert slot.material and slot.material.use_nodes
 for n in slot.material.node_tree.nodes:
  if n.type=='TEX_IMAGE' and n.image:
   assert n.image.packed_file;actual.add((hashlib.sha256(n.image.packed_file.data).hexdigest(),n.image.colorspace_settings.name))
assert actual==expected
for k,v in props.items():new[k]=v
new['original_asset_id']='B06W5XBL3D';new['original_asset_sha256']=row['source_sha256'];new['room_trial_source_revision']=79

for auxiliary in legacy_aux:bpy.data.objects.remove(auxiliary,do_unlink=True)
bpy.data.objects.remove(old,do_unlink=True);new.name=old_name
# Surface-intersection check for actual chair vs desk/storage meshes; no full3D navigation claim.
def bvh(o):
 ev=o.evaluated_get(bpy.context.evaluated_depsgraph_get());me=ev.to_mesh();p=[o.matrix_world@v.co for v in me.vertices];t=BVHTree.FromPolygons(p,[tuple(f.vertices) for f in me.polygons]);ev.to_mesh_clear();return t
nt=bvh(new);collisions=[]
for key in ['private_1_desk','private_1_credenza']:
 objects=[o for o in bpy.data.objects if o.type=='MESH' and o.get('program_key')==key];assert len(objects)==1;pairs=nt.overlap(bvh(objects[0]));collisions.append({'object':objects[0].name,'triangle_surface_intersections':len(pairs)});assert not pairs,collisions
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha and hashlib.sha256(prototype.read_bytes()).hexdigest()==proto_sha
views=json.loads((base/'review_views_delivery_r23.json').read_text());views=[v for v in views if v['name']=='private_office'];views.append({'name':'private_office_chair_front_detail','location':[2.1,3.25,1.15],'target':[2.5,4.25,.65],'hfov':65});(base/'review_views_private_chair_r84.json').write_text(json.dumps(views,indent=2)+'\n')
(ref/'realism_refinement_r84.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'prototype':str(prototype),'prototype_sha256':proto_sha,'original_asset_id':'B06W5XBL3D','original_glb_sha256':row['source_sha256'],'replaced_role':'private_1_chair','removed_legacy_auxiliary_parts':removed_aux,'old_object_name':old_name,'old_xy':old_xy,'new_yaw_radians':new.rotation_euler.z,'orientation_basis':'Two studio views show native front along-Y;rotate+pi/2 toexisting+X factoryfront convention,thenoldyaw.','source_extents_m':list(hi-lo),'scale_changed':False,'floor_hit_m':list(hit),'actual_floor_gap_m':min(v.z for v in points)-hit.z,'triangle_intersection_checks':collisions,'original_packed_png_hashes_and_colorspace_verified':True,'changes':'One chair mesh replaced withoriginal actualproduct andnative4kPBR;rigid coordinate normalization/pose only. Existing role/name/position retained. Allother meshes,materials,lights,world andcameras unchanged.','photorealism_accepted':False,'scope':'Bounded product-chair trial. Does not certify full3D navigation,allotherchairroles,closed-volume penetration,ergonomics orphoto/reference pass.'},indent=2)+'\n');print('Saved actual product-chair room trial84',flush=True)
