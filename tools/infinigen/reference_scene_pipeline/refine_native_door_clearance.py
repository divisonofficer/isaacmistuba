"""Refit duplicated native paired leaves to their casing; choose clear open states.
Native panel/handle geometry and materials are retained. Sources are immutable.
"""
import bpy,json,math,hashlib,itertools
from pathlib import Path
from mathutils import Vector
from shapely.geometry import MultiPoint,LineString
from shapely.ops import unary_union
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';source=base/'scene_candidate_r20.blend';out=base/'scene_candidate_r22.blend';assert not out.exists();digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();before=digest(source);bpy.ops.wm.open_mainfile(filepath=str(source))
selected=['LiteDoorFactory(7699791).spawn_asset(5)','LiteDoorFactory(800570).spawn_asset(6)']
for name in selected:bpy.data.objects.remove(bpy.data.objects[name],do_unlink=True)
with bpy.data.libraries.load(str(base/'scene_candidate_r19.blend'),link=False) as (src,dst):dst.objects=list(selected)
for obj in dst.objects:bpy.context.scene.collection.objects.link(obj)
def components(o):
 adj=[[] for v in o.data.vertices]
 for e in o.data.edges:a,b=e.vertices;adj[a].append(b);adj[b].append(a)
 seen=set();rows=[]
 for i in range(len(adj)):
  if i in seen:continue
  stack=[i];seen.add(i);comp=[]
  while stack:
   j=stack.pop();comp.append(j)
   for k in adj[j]:
    if k not in seen:seen.add(k);stack.append(k)
  rows.append(comp)
 return rows
def section(o,z):
 vs=[o.matrix_world@v.co for v in o.data.vertices];segments=[]
 for p in o.data.polygons:
  cs=[vs[i] for i in p.vertices];cross=[]
  for j,u in enumerate(cs):
   v=cs[(j+1)%len(cs)]
   if (u.z-z)*(v.z-z)<0:
    t=(z-u.z)/(v.z-u.z);cross.append((u.x+t*(v.x-u.x),u.y+t*(v.y-u.y)))
  if len(cross)>=2:segments.append(LineString(cross).buffer(.001))
 return unary_union(segments)
fixtures=[]
for o in bpy.data.objects:
 if o.type!='MESH' or o.get('reference_scene_owner')!='dual_unit_residential_floor_03':continue
 if o.get('audit_kind','furniture') not in ('furniture','ground_container','fixture'):continue
 vs=[o.matrix_world@Vector(c) for c in o.bound_box]
 if max(v.z for v in vs)<.45 or min(v.z for v in vs)>1.8:continue
 fixtures.append((o.name,MultiPoint([(v.x,v.y) for v in vs]).convex_hull))
records=[]
for o in list(bpy.data.objects):
 if o.type!='MESH' or o.name not in selected:continue
 casing=bpy.data.objects.get(o.name.replace('LiteDoorFactory','DoorCasingFactory'));assert casing,o.name
 used={i for p in o.data.polygons for i in p.vertices};raw=[v.co.copy() for v in o.data.vertices];ys=[raw[i].y for i in used];y0,y1=min(ys),max(ys);mid=(y0+y1)/2
 # The casing's inner opening is twice the original single-leaf hinge offset.
 aperture=abs(o.location.x)*2;assert .75<aperture<1.25,(o.name,aperture)
 width=y1-y0;scale=(aperture+.04)/width
 groups=components(o);leaf_indices=[[],[]];fixed=[]
 for comp in groups:
  cys=[raw[i].y for i in comp];span=max(cys)-min(cys)
  if len(comp)>1 and span<width*.75:
   side=0 if sum(cys)/len(cys)>mid else 1;leaf_indices[side].extend(comp)
  else:fixed.extend(comp)
 assert min(map(len,leaf_indices))>200,(o.name,list(map(len,leaf_indices)))
 closed=[Vector((-(v.y-mid)*scale,v.x,v.z)) for v in raw];hinges=[Vector((-aperture/2,0,0)),Vector((aperture/2,0,0))];matrix=casing.matrix_world.copy()
 def pose(signs,frac=1):
  vs=[v.copy() for v in closed]
  for idx,sign in enumerate(signs):
   angle=math.radians(sign)*frac;c=math.cos(angle);s=math.sin(angle);h=hinges[idx]
   for i in leaf_indices[idx]:
    d=vs[i]-h;vs[i].x=h.x+c*d.x-s*d.y;vs[i].y=h.y+s*d.x+c*d.y
  return vs
 def leaf_hulls(vs):
  return [MultiPoint([((matrix@vs[i]).x,(matrix@vs[i]).y) for i in inds]).convex_hull for inds in leaf_indices]
 trials=[]
 for signs in itertools.product((-90,-60,-45,45,60,90),repeat=2):
  gap=aperture-aperture*.5*sum(math.cos(math.radians(x)) for x in signs)
  if gap<.50:continue
  overlaps=[]
  for frac in (0,.25,.5,.75,1):
   shapes=leaf_hulls(pose(signs,frac));hits=[(name,sum(h.intersection(f).area for h in shapes)) for name,f in fixtures if f.distance(MultiPoint([(matrix@Vector((0,0,0))).xy]))<2]
   overlaps.append(sum(area for _,area in hits))
  shapes=leaf_hulls(pose(signs));leaf_overlap=shapes[0].intersection(shapes[1]).area
  trials.append((sum(overlaps)+100*leaf_overlap,signs,overlaps,leaf_overlap))
 score,signs,overlaps,leaf_overlap=min(trials,key=lambda x:x[0]);new=pose(signs);oldmatrix=[list(r) for r in o.matrix_world]
 o.data=o.data.copy()
 for v,co in zip(o.data.vertices,new):v.co=co
 o.parent=None;o.matrix_world=matrix;o.data.update();o['native_door_refit']=True;o['door_state']='paired_leaves_open_clearance_optimized';o['door_opening_width_m']=aperture
 aftershapes=leaf_hulls(new);hits=[{'object':name,'area_m2':sum(h.intersection(f).area for h in aftershapes)} for name,f in fixtures if any(h.intersects(f) for h in aftershapes)]
 records.append({'door':o.name,'casing':casing.name,'original_matrix':oldmatrix,'source_face_width_m':width,'opening_width_m':aperture,'width_scale':scale,'native_vertex_count':len(raw),'native_polygon_count':len(o.data.polygons),'leaf_vertices':list(map(len,leaf_indices)),'open_angles_deg':signs,'clear_opening_width_m':aperture-aperture*.5*sum(math.cos(math.radians(x)) for x in signs),'sampled_sweep_fixture_overlap_m2':overlaps,'open_leaf_self_overlap_m2':leaf_overlap,'open_fixture_hits':hits,'visual_review_pending':True})
assert len(records)==2,('Expected two repaired doors',len(records))
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert digest(source)==before
(ref/'native_door_fit_r22.json').write_text(json.dumps({'source':str(source),'source_sha256':before,'candidate':str(out),'candidate_sha256':digest(out),'source_unchanged':True,'doors':records,'limitations':['Fixture convex envelopes and five sampled swing states; not an exhaustive swept-volume certification.','Native casing frames unchanged. Other factory families await separate door audit.'],'visual_acceptance':False},indent=2));print(json.dumps({'doors':len(records),'candidate':str(out)}),flush=True)
