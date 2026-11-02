"""One-room actual product sofa trial. No scale deformation, relighting or promotion."""
import bpy,json,hashlib,math,datetime
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[3];ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';src=base/'scene_candidate_r73.blend';out=base/'scene_candidate_r76.blend';studio=ref/'real_living_candidates/review_studio.blend';assert not out.exists();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();before=sha(src);prototype_sha=sha(studio);scope=json.loads((ref/'real_living_candidates/review_scope.json').read_text());entry=next(x for x in scope['assets'] if x['id']=='B07B4MHRC1');native=next(x for x in json.loads((ref/'real_living_candidates/asset_candidates_manifest.json').read_text())['assets'] if x['id']==entry['id']);bpy.ops.wm.open_mainfile(filepath=str(src));bpy.context.view_layer.update();old=next(o for o in bpy.context.scene.objects if o.get('program_key')=='101_living_sectional');oldname=old.name;oldprops=dict(old.items());oldbounds=[old.matrix_world@Vector(p) for p in old.bound_box];oldlo=Vector(tuple(min(p[k] for p in oldbounds) for k in range(3)));oldhi=Vector(tuple(max(p[k] for p in oldbounds) for k in range(3)))
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
obj['original_asset_id']=entry['id'];obj['original_asset_sha256']=entry['source_sha256'];obj['asset_source']='ABO original product model';obj['refinement_revision']=76;bpy.context.view_layer.update();world=[obj.matrix_world@v.co for v in mesh.vertices];lo=Vector(tuple(min(p[k] for p in world) for k in range(3)));hi=Vector(tuple(max(p[k] for p in world) for k in range(3)));assert lo.x>=oldlo.x-1e-5 and hi.x<=oldhi.x+1e-5 and lo.y>=oldlo.y-1e-5 and hi.y<=oldhi.y+1e-5,(lo,hi,oldlo,oldhi)
# Measure actual floor rays from all original lowest vertices; contact is not whole-room navigation.
dg=bpy.context.evaluated_depsgraph_get();feet=[p for p in world if p.z<=lo.z+.00002];contacts=[]
for p in feet:
 ok,hit,normal,face,other,matrix=bpy.context.scene.ray_cast(dg,p+Vector((0,0,.0001)),Vector((0,0,-1)),distance=.02)
 # Avoid self hit by casting upward from below: actual floor surface must be immediately below the feet.
 if other==obj or not ok:
  ok,hit,normal,face,other,matrix=bpy.context.scene.ray_cast(dg,p-Vector((0,0,.0001)),Vector((0,0,-1)),distance=.02)
 if ok:contacts.append({'object':other.name,'gap_m':p.z-hit.z})
assert contacts and max(abs(c['gap_m']) for c in contacts)<.002,contacts
# Actual triangle overlap against living-room furnishings with keys,excluding intended rug and unkeyed architectural floor.
def tree(o):
 ev=o.evaluated_get(dg);me=ev.to_mesh();v=[o.matrix_world@x.co for x in me.vertices];polys=[list(f.vertices) for f in me.polygons];t=BVHTree.FromPolygons(v,polys);ev.to_mesh_clear();return t
own=tree(obj);overlaps=[]
for o in bpy.context.scene.objects:
 key=o.get('program_key','')
 if o==obj or o.type!='MESH' or not key.startswith('101_living') or key=='101_living_rug':continue
 bb=[o.matrix_world@Vector(p) for p in o.bound_box];a=Vector(tuple(min(p[k] for p in bb) for k in range(3)));b=Vector(tuple(max(p[k] for p in bb) for k in range(3)))
 if any(hi[k]<a[k] or lo[k]>b[k] for k in range(3)):continue
 n=len(own.overlap(tree(o)));overlaps.append({'object':o.name,'key':key,'triangle_overlap_pairs':n});assert n==0,(key,n)
assert sha(src)==before and sha(studio)==prototype_sha;bpy.ops.wm.save_as_mainfile(filepath=str(out));meta={'source':str(src),'source_sha256':before,'candidate':str(out),'candidate_sha256':sha(out),'prototype':str(studio),'prototype_sha256':prototype_sha,'asset_id':entry['id'],'asset_sha256':entry['source_sha256'],'images_verified_byte_exact':images,'changes':'101 living sofa only: replace superseded whole assembly and its owned detail children with real product mesh and original PBR. Rigid rotation/translation only; original size retained. No decorative cushion stand-ins. Other rooms/lights/exposure untouched.','old_world_bounds':[list(oldlo),list(oldhi)],'new_world_bounds':[list(lo),list(hi)],'new_extents_m':list(hi-lo),'removed_owned_objects':removed,'floor_contacts':contacts,'bounded_furniture_triangle_overlap':overlaps,'photorealism_accepted':False,'retained_revision':73,'limitation':'Contained within previous sofa footprint and bounded furniture overlap checks only; whole-room walls, moving doors, whole-floor navigation and photographic acceptance still require validation.'};(ref/'realism_refinement_r76.json').write_text(json.dumps(meta,indent=2)+'\n');print('REAL_SOFA_R76_SAVED',flush=True)
