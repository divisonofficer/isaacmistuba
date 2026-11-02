"""One-room actual product sofa trial. No scale deformation, relighting or promotion."""
import bpy,json,hashlib,math,datetime
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[3];ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';src=base/'scene_candidate_r73.blend';out=base/'scene_candidate_r77.blend';studio=ref/'real_living_right_sofa_candidate/review_studio.blend';assert not out.exists();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();before=sha(src);prototype_sha=sha(studio);scope=json.loads((ref/'real_living_right_sofa_candidate/review_scope.json').read_text());entry=next(x for x in scope['assets'] if x['id']=='B07B4N11J2');native=next(x for x in json.loads((ref/'real_living_right_sofa_candidate/asset_candidates_manifest.json').read_text())['assets'] if x['id']==entry['id']);bpy.ops.wm.open_mainfile(filepath=str(src));bpy.context.view_layer.update();old=next(o for o in bpy.context.scene.objects if o.get('program_key')=='101_living_sectional');oldname=old.name;oldprops=dict(old.items());oldbounds=[old.matrix_world@Vector(p) for p in old.bound_box];oldlo=Vector(tuple(min(p[k] for p in oldbounds) for k in range(3)));oldhi=Vector(tuple(max(p[k] for p in oldbounds) for k in range(3)))
# Import actual studio object; preserve the evaluated original rigid geometry, UV and PBR.
with bpy.data.libraries.load(str(studio),link=False) as (a,b):b.objects=entry['objects']
objects=b.objects;assert len(objects)==1;obj=objects[0];bpy.context.scene.collection.objects.link(obj);bpy.context.view_layer.update();mesh=obj.data.copy();mesh.transform(obj.matrix_world);pts=[v.co for v in mesh.vertices];lo=Vector(tuple(min(p[k] for p in pts) for k in range(3)));hi=Vector(tuple(max(p[k] for p in pts) for k in range(3)));mesh.transform(Matrix.Translation(Vector((-(lo.x+hi.x)/2,-(lo.y+hi.y)/2,-lo.z))));obj.parent=None;obj.data=mesh;obj.matrix_world=Matrix.Rotation(math.pi/2,4,'Z');bpy.context.view_layer.update();rotpts=[obj.matrix_world@v.co for v in mesh.vertices];rlo=Vector(tuple(min(p[k] for p in rotpts) for k in range(3)));rhi=Vector(tuple(max(p[k] for p in rotpts) for k in range(3)));obj.location=Vector((oldlo.x-rlo.x,(oldlo.y+oldhi.y-rlo.y-rhi.y)/2,oldlo.z-rlo.z));bpy.context.view_layer.update()
# Native byte checks on every live material texture; no synthetic material substitute.
image_by_sha={x['sha256']:x for x in native['native_images']};images=[]
for mat in obj.data.materials:
 assert mat and mat.use_nodes
 for node in mat.node_tree.nodes:
  if node.type!='TEX_IMAGE' or not node.image:continue
  im=node.image;assert im.packed_file;digest=hashlib.sha256(bytes(im.packed_file.data)).hexdigest();assert digest in image_by_sha,(im.name,digest);images.append({'name':im.name,'sha256':digest,'colorspace':im.colorspace_settings.name})
assert len(set(i['sha256'] for i in images))==3
# Preserve actual native cloth accent assemblies; refit against the new product's surfaces below.
pillows=[o for o in old.children if o.get('program_key','').startswith('101_native_sofa_pillow_')];assert len(pillows)==2
for pillow in pillows:
 pose=pillow.matrix_world.copy();pillow.parent=None;pillow.matrix_world=pose
removed=[]
def remove_tree(o):
 for ch in list(o.children):remove_tree(ch)
 removed.append({'name':o.name,'program_key':o.get('program_key','')});bpy.data.objects.remove(o,do_unlink=True)
remove_tree(old)
# Independently keyed legacy seat/back piping belongs to the superseded sofa.
for o in list(bpy.context.scene.objects):
 key=o.get('program_key','')
 if key.startswith('101_') and any(s in key for s in ['_seat_welt_native_','_back_welt_native_','_native_chaise_base','_native_chaise_foot_']):remove_tree(o)
obj.name=oldname
for k in ['program_key','reference_scene_owner','audit_kind']:
 if k in oldprops:obj[k]=oldprops[k]
obj['original_asset_id']=entry['id'];obj['original_asset_sha256']=entry['source_sha256'];obj['asset_source']='ABO original product model';obj['refinement_revision']=77;bpy.context.view_layer.update();world=[obj.matrix_world@v.co for v in mesh.vertices];lo=Vector(tuple(min(p[k] for p in world) for k in range(3)));hi=Vector(tuple(max(p[k] for p in world) for k in range(3)));assert lo.x>=.11 and hi.x<=6.89 and lo.y>=6.11 and hi.y<=9.39,(lo,hi)  # Actual101 living polygon, not previous sofa footprint.
# Measure actual floor rays from all original lowest vertices; contact is not whole-room navigation.
dg=bpy.context.evaluated_depsgraph_get();feet=[p for p in world if p.z<=lo.z+.00002];contacts=[];scene_ray_probes=[]
floor=bpy.data.objects['living-room_0/0.floor'];ev=floor.evaluated_get(dg);fm=ev.to_mesh();floor_tree=BVHTree.FromPolygons([floor.matrix_world@v.co for v in fm.vertices],[list(f.vertices) for f in fm.polygons]);ev.to_mesh_clear()
for p in feet:
 ok,hit,normal,face,other,matrix=bpy.context.scene.ray_cast(dg,p+Vector((0,0,.0001)),Vector((0,0,-1)),distance=.02)
 scene_ray_probes.append({'hit':ok,'object':other.name if other else None,'self_hit':other==obj})
 hit,normal,face,distance=floor_tree.ray_cast(p+Vector((0,0,.01)),Vector((0,0,-1)),.05)
 if hit is not None:contacts.append({'object':floor.name,'gap_m':p.z-hit.z,'method':'actual evaluated floor-only BVH, no self occlusion'})
(ref/'floor_contact_probe_r77.json').write_text(json.dumps({'source_revision':73,'asset':entry['id'],'scene_ray_probes':scene_ray_probes,'evaluated_floor_contacts':contacts,'scope':'Minimum-height native foot vertices only, not all-leg loading/contact certification.'},indent=2)+'\n')
assert len(contacts)==len(feet) and contacts and max(abs(c['gap_m']) for c in contacts)<.002,contacts
# Refit retained native cloth cushions with their existing seam children; no decorative stand-in boxes.
verts=world;polys=[list(f.vertices) for f in mesh.polygons];normal_matrix=obj.matrix_world.to_3x3().inverted().transposed();seat_faces=[];back_faces=[]
for face in mesh.polygons:
 normal=(normal_matrix@face.normal).normalized();center=obj.matrix_world@face.center
 if normal.z>.35 and lo.z+.25<center.z<lo.z+.65 and center.x>lo.x+.25:seat_faces.append(list(face.vertices))
 if normal.x>.3 and center.z>lo.z+.4 and center.x<lo.x+.6:back_faces.append(list(face.vertices))
assert seat_faces and back_faces
seat=BVHTree.FromPolygons(verts,seat_faces);back=BVHTree.FromPolygons(verts,back_faces);pillow_records=[]
for pillow in pillows:
 start=pillow.matrix_world.copy();center=start.translation.copy();offsets=[start@v.co-center for v in pillow.data.vertices];cx,cy,cz=center
 for iteration in range(5):
  zs=[]
  for q in offsets:
   hit,_,_,_=seat.ray_cast(Vector((cx+q.x,cy+q.y,2)),Vector((0,0,-1)),3)
   if hit is not None:zs.append(hit.z-q.z+.0007)
  assert zs,pillow.name;cz=max(zs);xs=[]
  for q in offsets:
   hit,_,_,_=back.ray_cast(Vector((4,cy+q.y,cz+q.z)),Vector((-1,0,0)),5)
   if hit is not None:xs.append(hit.x-q.x+.0007)
  assert xs,pillow.name;cx=max(xs)
 placed=[q+Vector((cx,cy,cz)) for q in offsets];tree_p=BVHTree.FromPolygons(placed,[list(f.vertices) for f in pillow.data.polygons]);overlap={'seat':len(tree_p.overlap(seat)),'back':len(tree_p.overlap(back))};gaps={'seat':min(seat.find_nearest(q)[3] for q in placed),'back':min(back.find_nearest(q)[3] for q in placed)};assert not any(overlap.values()) and max(gaps.values())<.003,(pillow.name,overlap,gaps)
 start.translation=Vector((cx,cy,cz));pillow.parent=obj;pillow.matrix_world=start;pillow_records.append({'object':pillow.name,'world_center':list(start.translation),'triangle_overlap_pairs':overlap,'minimum_vertex_surface_gaps_m':gaps,'native_cloth_mesh_and_seams_preserved':True})
# Actual triangle overlap against living-room furnishings with keys,excluding intended rug and unkeyed architectural floor.
def tree(o):
 ev=o.evaluated_get(dg);me=ev.to_mesh();v=[o.matrix_world@x.co for x in me.vertices];polys=[list(f.vertices) for f in me.polygons];t=BVHTree.FromPolygons(v,polys);ev.to_mesh_clear();return t
own=tree(obj);overlaps=[]
for o in bpy.context.scene.objects:
 key=o.get('program_key','')
 if o==obj or o.type!='MESH' or (not key.startswith('101_living') and not o.name.endswith(('.wall','.exterior'))) or key=='101_living_rug':continue
 bb=[o.matrix_world@Vector(p) for p in o.bound_box];a=Vector(tuple(min(p[k] for p in bb) for k in range(3)));b=Vector(tuple(max(p[k] for p in bb) for k in range(3)))
 if any(hi[k]<a[k] or lo[k]>b[k] for k in range(3)):continue
 n=len(own.overlap(tree(o)));overlaps.append({'object':o.name,'key':key,'triangle_overlap_pairs':n});assert n==0,(key,n)
assert sha(src)==before and sha(studio)==prototype_sha;bpy.ops.wm.save_as_mainfile(filepath=str(out));meta={'source':str(src),'source_sha256':before,'candidate':str(out),'candidate_sha256':sha(out),'prototype':str(studio),'prototype_sha256':prototype_sha,'asset_id':entry['id'],'asset_sha256':entry['source_sha256'],'images_verified_byte_exact':images,'changes':'101 living sofa only: replace superseded whole assembly and its owned detail children with real product mesh and original PBR. Rigid rotation/translation only; original size retained. Retained two native cloth accent cushions and seams with measured seat/back refit; no new primitive props. Other rooms/lights/exposure untouched.','old_world_bounds':[list(oldlo),list(oldhi)],'new_world_bounds':[list(lo),list(hi)],'new_extents_m':list(hi-lo),'removed_owned_objects':removed,'floor_contacts':contacts,'bounded_furniture_and_wall_triangle_overlap':overlaps,'retained_native_pillow_refit':pillow_records,'photorealism_accepted':False,'retained_revision':73,'limitation':'Actual room bounds and bounded furniture/wall overlap checks only; whole-room walls, moving doors, whole-floor navigation and photographic acceptance still require validation.'};(ref/'realism_refinement_r77.json').write_text(json.dumps(meta,indent=2)+'\n');print('REAL_SOFA_R77_SAVED',flush=True)
