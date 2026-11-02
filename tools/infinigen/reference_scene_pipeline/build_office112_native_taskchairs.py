"""Replace all24 workstation chair stand-ins with an eligible actual task product."""
import bpy,json,hashlib,math
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';b=r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';src=b/'scene_candidate_r111_draft.blend';dst=b/'scene_candidate_r112_draft.blend';assert not dst.exists();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();before=sha(src);p=d/'real_chair_candidates';review=json.loads((p/'visual_review_fixed.json').read_text());assert review['decisions']['B06W5XBL3D']['room_trial_eligible'];studio=p/'review_studio_textures_fixed.blend';assert sha(studio)==review['source_sha256'];row=next(x for x in json.loads((p/'review_scope.json').read_text())['assets'] if x['id']=='B06W5XBL3D');assert len(row['objects'])==1;bpy.ops.wm.open_mainfile(filepath=str(src));oldchairs=[o for o in bpy.context.scene.objects if o.type=='MESH' and str(o.get('program_key','')).startswith('pod_') and '_chair' in str(o.get('program_key','')) and '_back' not in str(o.get('program_key',''))];oldchairs=[o for o in oldchairs if str(o.get('program_key')).split('_chair')[-1].isdigit()];assert len(oldchairs)==24
names=tuple(row['objects'])
with bpy.data.libraries.load(str(studio),link=False) as (a,z):z.objects=list(names)
proto=z.objects[0];bpy.context.scene.collection.objects.link(proto);bpy.context.view_layer.update();proto.data=proto.data.copy();proto.data.transform(proto.matrix_world);proto.parent=None;proto.matrix_world=Matrix.Identity(4);ps=[v.co for v in proto.data.vertices];lo=Vector([min(v[k] for v in ps) for k in range(3)]);hi=Vector([max(v[k] for v in ps) for k in range(3)]);assert max(abs((hi-lo)[k]-row['original_world_extents_m'][k]) for k in range(3))<1e-5;proto.data.transform(Matrix.Translation(Vector((-(lo.x+hi.x)/2,-(lo.y+hi.y)/2,-lo.z))))
def tree(o):return BVHTree.FromPolygons([o.matrix_world@v.co for v in o.data.vertices],[tuple(f.vertices) for f in o.data.polygons])
floor=bpy.data.objects['office_0/9.floor'];ft=tree(floor);desk_trees={};rows=[];newchairs=[]
for old in sorted(oldchairs,key=lambda x:x['program_key']):
 key=str(old['program_key']);oldmatrix=old.matrix_world.copy();props={k:old[k] for k in old.keys()};members={old}|set(old.children_recursive)|{o for o in bpy.context.scene.objects if str(o.get('program_key','')).startswith(key+'_')};deskkey=key.split('_chair')[0];desk=next(o for o in bpy.context.scene.objects if o.get('program_key')==deskkey)
 if deskkey not in desk_trees:desk_trees[deskkey]=tree(desk)
 pos=oldmatrix.translation;support=ft.ray_cast(Vector((pos.x,pos.y,1)),Vector((0,0,-1)),2)[0];assert support is not None
 new=proto.copy();new.data=proto.data;bpy.context.scene.collection.objects.link(new);new.name='Office112_native_task_'+key;new.parent=None;new.matrix_world=Matrix.Translation(Vector((pos.x,pos.y,support.z)))@oldmatrix.to_quaternion().to_matrix().to_4x4()@Matrix.Rotation(math.pi/2,4,'Z')
 for k in list(new.keys()):del new[k]
 for k,v in props.items():new[k]=v
 new['original_asset_id']='B06W5XBL3D';new['replacement_revision']=112;new['native_source_sha256']=row['source_sha256'];bpy.context.view_layer.update();t=tree(new);pairs=t.overlap(desk_trees[deskkey]);assert not pairs,(key,'native chair intersects desk',len(pairs));world=[new.matrix_world@v.co for v in new.data.vertices];minz=min(v.z for v in world);assert abs(minz-support.z)<1e-5
 contacts=[]
 for q in world:
  if q.z>minz+.001:continue
  hit=ft.ray_cast(q+Vector((0,0,.1)),Vector((0,0,-1)),.2)[0];assert hit is not None;gap=q.z-hit.z;assert -.00001<=gap<=.0011;contacts.append(gap)
 assert contacts
 removed=[o.name for o in members]
 for o in members:bpy.data.objects.remove(o,do_unlink=True)
 newchairs.append(new);rows.append({'key':key,'removed':removed,'native_asset':'B06W5XBL3D','native_extents_m':list(hi-lo),'scale':list(new.scale),'floor_z_m':support.z,'low_wheel_samples':len(contacts),'max_support_gap_m':max(contacts),'own_desk_surface_intersections':len(pairs),'matrix':[list(x) for x in new.matrix_world]})
bpy.data.objects.remove(proto,do_unlink=True);chair_trees=[tree(o) for o in newchairs];chair_collisions=[]
for i in range(len(newchairs)):
 for j in range(i+1,len(newchairs)):
  if (newchairs[i].location-newchairs[j].location).length>1.2:continue
  n=len(chair_trees[i].overlap(chair_trees[j]));assert not n,(newchairs[i].name,newchairs[j].name,n);chair_collisions.append({'a':newchairs[i].name,'b':newchairs[j].name,'intersections':n})
bpy.ops.wm.save_as_mainfile(filepath=str(dst));assert sha(src)==before;(d/'taskchairs112_build.json').write_text(json.dumps({'source':str(src),'source_sha256':before,'candidate':str(dst),'candidate_sha256':sha(dst),'prototype_studio':str(studio),'prototype_studio_sha256':sha(studio),'native_asset':'B06W5XBL3D','replaced_chairs':rows,'nearby_chair_pair_checks':chair_collisions,'native_fabric_color_retained':'charcoal; blue reference palette unresolved','scope':'Native rigid-only geometry/UV/materials, same24 positions/yaws, floor wheel support, own-desk and nearby chair raw surface checks only. No full navigation, closed-volume/evaluated-modifier certification or visual acceptance.','accepted':False},indent=2));print('OFFICE112_NATIVE24_TASKCHAIRS_SAVED')
