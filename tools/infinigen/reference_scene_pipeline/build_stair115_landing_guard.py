"""Actual continuous landing guard returning into sloped rail, source-specific support proof."""
import bpy,bmesh,json,math,hashlib
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';b=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';src=b/'scene_candidate_r114_draft.blend';dst=b/'scene_candidate_r115_draft.blend';assert not dst.exists();bpy.ops.wm.open_mainfile(filepath=str(src));fz=max((bpy.data.objects['bedroom_0/0.floor'].matrix_world@Vector(c)).z for c in bpy.data.objects['bedroom_0/0.floor'].bound_box);level=fz+2.7;railz=level+.92;mat=bpy.data.materials['Residential112_painted_steel_guard'];path=[Vector((9.09,12.05,railz)),Vector((11.04,12.05,railz))]
for i in range(1,17):
 theta=-math.pi/2+(math.pi/2)*i/16;path.append(Vector((11.04+.06*math.cos(theta),12.11+.06*math.sin(theta),railz)))
path.append(Vector((11.1,12.22,railz)));N=64;verts=[]
for j,p in enumerate(path):
 tangent=(path[min(j+1,len(path)-1)]-path[max(j-1,0)]).normalized();normal=Vector((-tangent.y,tangent.x,0));up=Vector((0,0,1))
 for i in range(N):a=math.tau*i/N;verts.append(p+.025*(math.cos(a)*normal+math.sin(a)*up))
faces=[]
for j in range(len(path)-1):
 for i in range(N):faces.append((j*N+i,j*N+(i+1)%N,(j+1)*N+(i+1)%N,(j+1)*N+i))
faces.extend([tuple(reversed(range(N))),tuple((len(path)-1)*N+i for i in range(N))]);me=bpy.data.meshes.new('Stair115_continuous_guard_tube');me.from_pydata(verts,[],faces);bm=bmesh.new();bm.from_mesh(me);bmesh.ops.recalc_face_normals(bm,faces=bm.faces);assert all(e.is_manifold for e in bm.edges);bm.to_mesh(me);bm.free();rail=bpy.data.objects.new(me.name,me);bpy.context.scene.collection.objects.link(rail);me.materials.append(mat)
for f in me.polygons:f.use_smooth=len(f.vertices)==4
rail['audit_kind']='stair_guard';rail['program_key']='upper_landing_continuous_guard'
proto=next(o for o in bpy.context.scene.objects if o.type=='MESH' and o.get('audit_kind')=='stair_guard' and 'post' in o.name.lower());data=proto.data.copy();data.transform(proto.matrix_world);ps=[v.co for v in data.vertices];lo=Vector([min(v[k] for v in ps) for k in range(3)]);hi=Vector([max(v[k] for v in ps) for k in range(3)]);assert abs(hi.z-lo.z-.92)<.005;data.transform(Matrix.Translation(Vector((-(lo.x+hi.x)/2,-(lo.y+hi.y)/2,-lo.z))));posts=[]
for i in range(14):
 x=9.18+i*.14;o=bpy.data.objects.new(f'Stair115_upper_landing_post_{i:02}',data);bpy.context.scene.collection.objects.link(o);o.matrix_world=Matrix.Translation(Vector((x,12.05,level)));o['audit_kind']='stair_guard';o['program_key']='upper_landing_guard_post';posts.append(o)
bpy.context.view_layer.update();vs=[];fs=[]
for o in bpy.context.scene.objects:
 if o.type!='MESH' or o.get('audit_kind')!='stair_structure':continue
 offset=len(vs);vs.extend(o.matrix_world@v.co for v in o.data.vertices);fs.extend(tuple(offset+i for i in f.vertices) for f in o.data.polygons)
t=BVHTree.FromPolygons(vs,fs);checks=[]
for o in posts:
 points=[o.matrix_world@v.co for v in o.data.vertices];low=min(v.z for v in points);gaps=[]
 for q in points:
  if q.z>low+.0001:continue
  hit=t.ray_cast(q+Vector((0,0,.02)),Vector((0,0,-1)),.1)[0];assert hit is not None;gaps.append(q.z-hit.z)
 assert max(abs(x) for x in gaps)<.001;checks.append({'post':o.name,'support_samples':len(gaps),'max_abs_gap_m':max(abs(x) for x in gaps)})
# Actual sloped rail endpoint must meet the return, not merely look adjacent.
ends=[]
for o in bpy.context.scene.objects:
 if o.type!='MESH' or 'continuous_handrail' not in o.name:continue
 for z in [min(v.co.z for v in o.data.vertices),max(v.co.z for v in o.data.vertices)]:ends.append((o.name,o.matrix_world@Vector((0,0,z))))
nearest=min(ends,key=lambda x:(x[1]-path[-1]).length);gap=(nearest[1]-path[-1]).length;assert gap<.003,(nearest,gap)
bpy.ops.wm.save_as_mainfile(filepath=str(dst));(d/'stair115_landing_guard.json').write_text(json.dumps({'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'candidate':str(dst),'candidate_sha256':hashlib.sha256(dst.read_bytes()).hexdigest(),'new_posts':checks,'guard_tube_radius_m':.025,'elbow_centerline_radius_m':.06,'sloped_rail_endpoint':nearest[0],'endpoint_gap_m':gap,'post_center_spacing_m':.14,'exit_route_nominal_clear_width_m':.95,'scope':'Continuous landing guard/return,14 native copied stanchions with actual support rays, endpoint continuity. No anchors, guard-gap/code/load certification, full door swing/nav or visual acceptance.','accepted':False},indent=2));print('STAIR115_LANDING_GUARD_SAVED')
