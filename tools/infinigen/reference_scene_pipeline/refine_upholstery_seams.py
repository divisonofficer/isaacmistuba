"""Add real seat-cushion welt geometry following the actual native mesh surface."""
import bpy,json,hashlib,math
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';source=base/'scene_candidate_r29.blend';out=base/'scene_candidate_r30.blend';assert not out.exists();before=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source));records=[]
for unit in (101,102):
 o=next(o for o in bpy.data.objects if o.get('program_key')==f'{unit}_living_sectional');slot=next(i for i,m in enumerate(o.data.materials) if m and m.name=='ir_sec_cushion');faces=[f for f in o.data.polygons if f.material_index==slot];ids={i for f in faces for i in f.vertices};adj={i:set() for i in ids}
 for f in faces:
  for i in f.vertices:adj[i].update(j for j in f.vertices if j!=i)
 seen=set();groups=[]
 for i in ids:
  if i in seen:continue
  stack=[i];seen.add(i);group=[]
  while stack:
   j=stack.pop();group.append(j)
   for k in adj[j]:
    if k not in seen:seen.add(k);stack.append(k)
  groups.append(group)
 for index,group in enumerate(groups):
  if len(group)<20:continue
  indexmap={i:j for j,i in enumerate(group)};vertices=[o.data.vertices[i].co.copy() for i in group];polygons=[[indexmap[i] for i in f.vertices] for f in faces if f.vertices[0] in indexmap];tree=BVHTree.FromPolygons(vertices,polygons);x0,x1=min(v.x for v in vertices),max(v.x for v in vertices);y0,y1=min(v.y for v in vertices),max(v.y for v in vertices);z0,z1=min(v.z for v in vertices),max(v.z for v in vertices);z=z0+(z1-z0)*.60;center=Vector(((x0+x1)/2,(y0+y1)/2,z));points=[];max_offset=0
  for k in range(96):
   theta=2*math.pi*k/96;radial=Vector(((x1-x0)*math.cos(theta),(y1-y0)*math.sin(theta),0));origin=center+radial;hit,normal,_,_=tree.ray_cast(origin,-radial.normalized(),radial.length*2)
   assert hit is not None,(unit,index,k)
   points.append(hit+normal*.0003)
  points.append(points[0]);data=bpy.data.curves.new('native_seat_welt','CURVE');data.dimensions='3D';data.bevel_depth=.00065;data.bevel_resolution=3;spline=data.splines.new('POLY');spline.points.add(len(points)-1)
  for dst,co in zip(spline.points,points):dst.co=(*co,1)
  seam=bpy.data.objects.new(f'FineR5_{unit}_seat_welt_{index}',data);bpy.context.scene.collection.objects.link(seam);seam.parent=o;data.materials.append(o.data.materials[slot]);seam['reference_scene_owner']='dual_unit_residential_floor_03';seam['program_key']=f'{unit}_seat_welt_{index}';seam['audit_kind']='detail';seam['support_object']=o.name;records.append({'object':seam.name,'seam_radius_m':.00065,'surface_offset_m':.0003,'sampled_surface_contacts':96})
assert len(records)==8,len(records)
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(source.read_bytes()).hexdigest()==before;(ref/'realism_refinement_r30.json').write_text(json.dumps({'source':str(source),'candidate':str(out),'change':'Native seat-cushion welt curves follow96 actual mesh ray contacts per cushion, inset into textile rather than dark AO lines.','seams':records,'photorealism_accepted':False},indent=2));print(json.dumps({'saved':str(out),'seams':len(records)}),flush=True)
