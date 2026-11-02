"""Replace two101accent pillows with native curved product meshes, rigid fit only."""
import bpy,json,hashlib,math
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';B=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';S=B/'scene_candidate_r97.blend';O=B/'scene_candidate_r98.blend';assert not O.exists();sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();hs=sha(S)
P=D/'real_pillow_candidates';scope=json.loads((P/'scope.json').read_text());opt=json.loads((P/'plain_linen_scope.json').read_text());review=json.loads((P/'blind_plain_linen_review.json').read_text());assert review['plain_variant_merits_room_trial'];proto=P/'plain_linen_studio.blend';assert sha(proto)==opt['candidate_sha256'];hp=sha(proto)
bpy.ops.wm.open_mainfile(filepath=str(S));sofa=next(o for o in bpy.context.scene.objects if o.get('program_key')=='101_living_sectional');old=sorted([o for o in sofa.children if o.get('program_key','').startswith('101_native_sofa_pillow_')],key=lambda o:o.get('program_key'));assert len(old)==2
old_rows=[{'name':o.name,'properties':dict(o.items()),'matrix':[list(r) for r in o.matrix_world]} for o in old]
with bpy.data.libraries.load(str(proto),link=False) as (src,dst):dst.objects=[r['object'] for r in scope['objects']]
objects=list(dst.objects)
for o in objects:bpy.context.scene.collection.objects.link(o)
bpy.context.view_layer.update();world=[sofa.matrix_world@v.co for v in sofa.data.vertices];lo=Vector([min(p[k] for p in world) for k in range(3)]);nm=sofa.matrix_world.to_3x3().inverted().transposed();seat_faces=[];back_faces=[]
for f in sofa.data.polygons:
 n=(nm@f.normal).normalized();c=sofa.matrix_world@f.center
 if n.z>.35 and lo.z+.25<c.z<lo.z+.65 and c.x>lo.x+.25:seat_faces.append(tuple(f.vertices))
 if n.x>.3 and c.z>lo.z+.4 and c.x<lo.x+.6:back_faces.append(tuple(f.vertices))
assert seat_faces and back_faces;seat=BVHTree.FromPolygons(world,seat_faces);back=BVHTree.FromPolygons(world,back_faces);whole=BVHTree.FromPolygons(world,[tuple(f.vertices) for f in sofa.data.polygons]);records=[];removed=[]
def remove_owned(o):
 for ch in list(o.children):remove_owned(ch)
 removed.append(o.name);bpy.data.objects.remove(o,do_unlink=True)
for i,(o,prior) in enumerate(zip(objects,old_rows)):
 native=o.matrix_world.copy();pts=[native@v.co for v in o.data.vertices];center=Vector([(min(p[k] for p in pts)+max(p[k] for p in pts))/2 for k in range(3)]);o.parent=None
 o.matrix_world=Matrix.Translation(Vector(prior['matrix'][k][3] for k in range(3)))@Matrix.Rotation(math.pi/2,4,'Z')@Matrix.Translation(-center)@native
 matrix=o.matrix_world.copy();anchor=matrix.translation.copy();offsets=[matrix@v.co-anchor for v in o.data.vertices]
 # Vertex-only support missed surface crossing between vertices. Include triangle centres/edges.
 support=list(offsets)
 for face in o.data.polygons:
  ids=list(face.vertices);support.append(sum((offsets[j] for j in ids),Vector())/len(ids))
  for j,k in zip(ids,ids[1:]+ids[:1]):support.append((offsets[j]+offsets[k])*.5)
 cx,cy,cz=anchor
 for iteration in range(16):
  zs=[]
  for q in support:
   hit=seat.ray_cast(Vector((cx+q.x,cy+q.y,2)),Vector((0,0,-1)),3)[0]
   if hit is not None:zs.append(hit.z-q.z+.0012)
  assert zs;cz=max(zs);xs=[]
  for q in support:
   hit=back.ray_cast(Vector((4,cy+q.y,cz+q.z)),Vector((-1,0,0)),5)[0]
   if hit is not None:xs.append(hit.x-q.x+.0012)
  assert xs;cx=max(xs)
 matrix.translation=Vector((cx,cy,cz));o.matrix_world=matrix;pts=[matrix@v.co for v in o.data.vertices];own=BVHTree.FromPolygons(pts,[tuple(f.vertices) for f in o.data.polygons]);overlap={'seat':len(own.overlap(seat)),'back':len(own.overlap(back)),'whole_sofa':len(own.overlap(whole))};gaps={'seat':min(seat.find_nearest(p)[3] for p in pts),'back':min(back.find_nearest(p)[3] for p in pts)}
 assert not any(overlap.values()),(o.name,overlap);assert max(gaps.values())<.003,(o.name,gaps)
 original_name=o.name;o.name=f'Res03_r98_actual_pillow_{i}'
 for key,value in prior['properties'].items():o[key]=value
 o['asset_source']='PolyHaven actual cloth product mesh';o['original_asset_id']='PH_throw_pillows_01';o['refinement_revision']=98;o.parent=sofa;o.matrix_world=matrix
 records.append({'object':o.name,'prototype_object':original_name,'matrix':[list(v) for v in matrix],'prototype_matrix':[list(v) for v in native],'faces':len(o.data.polygons),'sofa':sofa.name,'triangle_surface_overlaps':overlap,'minimum_vertex_surface_gaps_m':gaps,'old_object':prior['name']})
for o in old:remove_owned(o)
assert sha(S)==hs and sha(proto)==hp;bpy.ops.wm.save_as_mainfile(filepath=str(O));meta=json.loads((D/'realism_refinement_r97.json').read_text());meta.update(source=str(S),source_sha256=hs,candidate=str(O),candidate_sha256=sha(O),change='Only101living two accent pillows and owned old seams replaced with actual native curved cloth products. Rigid placement, original shape/UV/normal/ORM, authored plain cream/sage palette. No light/camera/world changes; bathroom97 preserved.',actual_pillows={'prototype':str(proto),'prototype_sha256':hp,'records':records,'removed_owned_objects':removed,'native_source':scope['assets'][0],'optical_policy':opt['change'],'scope':'Seat/back and whole-sofa triangle-surface separation and vertex-nearest contact only. No closed-volume containment,load/cloth-simulation/full-room or photographic acceptance.'},photorealism_accepted=False);(D/'realism_refinement_r98.json').write_text(json.dumps(meta,indent=2))
