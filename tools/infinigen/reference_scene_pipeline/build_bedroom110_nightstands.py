"""Native-sized two-nightstand room trial; no dataset promotion."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Matrix,Vector
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';b=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';src=b/'scene_candidate_r108_draft.blend';dst=b/'scene_candidate_r110_draft.blend';assert not dst.exists();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();before=sha(src);p=d/'bedroom110_products';studio=p/'review_studio.blend';scope=json.loads((p/'review_scope.json').read_text());asset='HSSD_xxxx2d7fa89ax71d3x4ac7xb350xa294dd8ef99b';row=next(x for x in scope['assets'] if x['id']==asset);bpy.ops.wm.open_mainfile(filepath=str(src));olds=sorted([o for o in bpy.context.scene.objects if o.get('program_key')=='102_master_nightstand'],key=lambda o:o.name);assert len(olds)==2
with bpy.data.libraries.load(str(studio),link=False) as (a,z):z.objects=row['objects']
protos=z.objects
for o in protos:bpy.context.scene.collection.objects.link(o)
bpy.context.view_layer.update();coords=[o.matrix_world@v.co for o in protos for v in o.data.vertices];lo=Vector([min(v[k] for v in coords) for k in range(3)]);hi=Vector([max(v[k] for v in coords) for k in range(3)]);delta=Vector((-(lo.x+hi.x)/2,-(lo.y+hi.y)/2,-lo.z));meshes=[]
for o in protos:
 me=o.data.copy();me.transform(Matrix.Translation(delta)@o.matrix_world);meshes.append(me)
def bounds(o):
 ps=[o.matrix_world@v.co for v in o.data.vertices];return Vector([min(v[k] for v in ps) for k in range(3)]),Vector([max(v[k] for v in ps) for k in range(3)])
def tree(o):return BVHTree.FromPolygons([o.matrix_world@v.co for v in o.data.vertices],[tuple(f.vertices) for f in o.data.polygons])
rows=[]
for i,old in enumerate(olds):
 ol,oh=bounds(old);center=(ol+oh)/2;pos=Vector((center.x,center.y,ol.z));news=[]
 for j,me in enumerate(meshes):
  o=bpy.data.objects.new(f'Residential110_102_master_native_nightstand_{i}_{j}',me);bpy.context.scene.collection.objects.link(o);o.matrix_world=Matrix.Translation(pos);o['program_key']=f'102_master_nightstand_native_{i}';o['original_asset_id']=asset;news.append(o)
 bpy.context.view_layer.update();newtop=pos.z+(hi-lo).z;lampdelta=newtop-oh.z;moved=[]
 for o in list(bpy.context.scene.objects):
  if not str(o.get('program_key','')).startswith('102_master_nightstand_lamp'):continue
  # Local matching before translation prevents repeated movement of neighbouring lamp assemblies.
  q=o.matrix_world.translation
  if (Vector((q.x,q.y,0))-Vector((center.x,center.y,0))).length>.25:continue
  o.location.z+=lampdelta;moved.append(o.name)
 assert moved
 nearby=[]
 for o in bpy.context.scene.objects:
  if o.type!='MESH' or o in news or o in olds or o in protos or o.name in moved:continue
  key=str(o.get('program_key',''))
  if not key.startswith('102_master_bed'):continue
  count=sum(len(tree(n).overlap(tree(o))) for n in news);assert count==0,(o.name,count);nearby.append({'object':o.name,'raw_surface_intersections':count})
 for n in news:
  nl,nh=bounds(n);assert nl.x>12.615 and nh.x<16.385 and nl.y>14.115 and nh.y<17.885;assert abs(nl.z-ol.z)<1e-6
 rows.append({'old_object':old.name,'old_bounds':[list(ol),list(oh)],'new_objects':[o.name for o in news],'native_extents_m':list(hi-lo),'floor_z_m':ol.z,'lamp_translation_z_m':lampdelta,'lamp_objects_moved':moved,'nearby_bed_checks':nearby})
 bpy.data.objects.remove(old,do_unlink=True)
for o in protos:bpy.data.objects.remove(o,do_unlink=True)
bpy.ops.wm.save_as_mainfile(filepath=str(dst));assert sha(src)==before;(d/'bedroom110_build.json').write_text(json.dumps({'source':str(src),'source_sha256':before,'candidate':str(dst),'candidate_sha256':sha(dst),'prototype':str(studio),'prototype_sha256':sha(studio),'replacements':rows,'accepted':False,'scope':'102 master only, two actual native product nightstands; no rescale. Bed raw-surface overlap and rectangular room bounds checked. Lamps vertically repositioned to support. No full navigation/door sweep, shader equivalence or visual approval.'},indent=2));print('BEDROOM110_NATIVE_NIGHTSTANDS_SAVED')
