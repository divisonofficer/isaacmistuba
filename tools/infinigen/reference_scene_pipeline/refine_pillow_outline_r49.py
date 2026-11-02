"""Round the restored native pillow panel outline; retain native pressure loft and refit support."""
import bpy,json,hashlib,math
import numpy as np
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r48.blend';out=base/'scene_candidate_r49.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
def tree(mesh,faces):return BVHTree.FromPolygons([v.co.copy() for v in mesh.vertices],[list(f.vertices) for f in faces])
for unit in [101,102]:
 parent=next(o for o in bpy.data.objects if o.get('program_key')==f'{unit}_living_sectional');roles=parent.data.attributes['native_sofa_role'];seat=tree(parent.data,[f for f in parent.data.polygons if roles.data[f.index].value==1]);back=tree(parent.data,[f for f in parent.data.polygons if roles.data[f.index].value==2])
 for index in [0,1]:
  o=next(o for o in bpy.data.objects if o.get('program_key')==f'{unit}_native_sofa_pillow_{index}');o.data=o.data.copy();R=Matrix.Rotation(-.12,4,'Y')@Matrix.Rotation(-.15 if index==0 else -.19,4,'Y')@Matrix.Rotation(.08 if index==0 else -.07,4,'Z');inv=R.inverted();old=[inv@v.co for v in o.data.vertices];arr=np.asarray(old);center=(arr.min(0)+arr.max(0))/2;half=(arr.max(0)-arr.min(0))/2
  # Smooth square-to-rounded outline: corner recession, not an inflated box or new cloth simulation.
  # Native front/back pressure shape and small folds are retained. Extra loft is modest and central.
  def remap(v):
   p=inv@v;d,y,z=p-Vector(center);u=y/half[1];w=z/half[2];newy=y*math.sqrt(max(.1,1-.38*w*w));newz=z*math.sqrt(max(.1,1-.38*u*u));bell=max(0,1-u*u)*max(0,1-w*w);newd=d*(1+.12*bell)
   # Slight asymmetric panel fullness; continuous same transform for both panels and seam.
   newy+=.004*bell*w;return R@(Vector(center)+Vector((newd,newy,newz)))
  for v in o.data.vertices:v.co=remap(v.co)
  for seam in o.children:
   if seam.type!='CURVE':continue
   seam.data=seam.data.copy();seam.data.bevel_depth=.0010
   for spline in seam.data.splines:
    for p in spline.points:p.co=(*remap(Vector(p.co[:3])),1)
  o.data.update();positions=[v.co.copy() for v in o.data.vertices];yc=o.location.y;cx,cz=.55,.65
  for iteration in range(6):
   zs=[]
   for q in positions:
    hit,_,_,_=seat.ray_cast(Vector((q.x+cx,q.y+yc,2)),Vector((0,0,-1)),3)
    if hit is not None:zs.append(hit.z-q.z+.0005)
   assert zs;cz=max(zs);xs=[]
   for q in positions:
    hit,_,_,_=back.ray_cast(Vector((3,q.y+yc,q.z+cz)),Vector((-1,0,0)),3)
    if hit is not None:xs.append(hit.x-q.x+.0005)
   assert xs;cx=max(xs)
  location=Vector((cx,yc,cz));placed=[q+location for q in positions];body=BVHTree.FromPolygons(placed,[list(f.vertices) for f in o.data.polygons]);overlap={'seat':len(body.overlap(seat)),'back':len(body.overlap(back))};assert not any(overlap.values()),overlap;gaps={'seat':min(seat.find_nearest(q)[3] for q in placed),'back':min(back.find_nearest(q)[3] for q in placed)};assert max(gaps.values())<.003,gaps;o.location=location
  # Evaluate nonadjacent self-overlap with shared/coincident edge exclusions.
  local=tree(o.data,o.data.polygons);sets=[set(f.vertices) for f in o.data.polygons];coords=[{tuple(round(float(x),7) for x in o.data.vertices[i].co) for i in f.vertices} for f in o.data.polygons];pairs=[(i,j) for i,j in local.overlap(local) if j>i and not sets[i]&sets[j] and not coords[i]&coords[j]];assert not pairs,len(pairs)
  rows.append({'object':o.name,'native_prechange_depth_width_height_m':(half*2).tolist(),'outline_corner_coefficient':.38,'central_loft_multiplier':1.12,'piping_radius_m':.001,'contact_gap_m':gaps,'triangle_overlap_pairs':overlap,'nonadjacent_self_overlap_pairs':len(pairs),'new_center':list(location)})
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
(ref/'realism_refinement_r49.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'scope':'four native throw pillows outline/fullness and piping only;materials,camera,lighting unchanged','change':'Smooth rounded panel outline retaining native pressure loft/folds;modest central depth gain and thicker real piping. Refit actual seat/back supports. Not a new cloth solve or loaded deformation acceptance.','pillows':rows,'photorealism_accepted':False,'requires':'same-camera actual render and independent critique;lower load deformation remains unproven'},indent=2));print('SAVED',out,flush=True)
