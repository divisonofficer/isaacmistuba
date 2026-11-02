"""Choose review cameras against actual native door leaves; preserve scene geometry."""
import json,sys,math,argparse
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from shapely.geometry import MultiPoint,Point,LineString
from shapely.ops import unary_union
from tile_geometry import projected_floor
p=argparse.ArgumentParser();p.add_argument('--revision',type=int,default=19);a=p.parse_args();revision=a.revision
ROOT=Path(__file__).resolve().parents[3]
base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full'
ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
bpy.ops.wm.open_mainfile(filepath=str(base/f'scene_candidate_r{revision}.blend'))
views=json.loads((base/'review_views_delivery_r18.json').read_text());mapping=json.loads((ref/'room_mapping.json').read_text())
def pts(o):return [o.matrix_world@Vector(c) for c in o.bound_box]
def hull(o):return MultiPoint([(v.x,v.y) for v in pts(o)]).convex_hull
def center(o):return sum(pts(o),Vector())/8
def item(key):return next(o for o in bpy.data.objects if o.get('program_key')==key)
doors=[]
for o in bpy.data.objects:
 if o.type=='MESH' and 'DoorFactory' in o.name and 'casing' not in o.name.lower():
  verts=[o.matrix_world@v.co for v in o.data.vertices]
  if verts:doors.append((o,hull(o),BVHTree.FromPolygons(verts,[list(p.vertices) for p in o.data.polygons])))
records=[]
for key in ('102_bathroom1','102_laundry_wc'):
 floor=bpy.data.objects[mapping[key]['room_id']+'.floor'];domain=projected_floor(floor);fz=max(v.z for v in pts(floor));blockers=[];shower=item(key+'_shower');shower_inside=hull(shower).buffer(-.27)
 for o in bpy.data.objects:
  if o.type!='MESH' or o.get('reference_scene_owner')!='dual_unit_residential_floor_03':continue
  kind=o.get('audit_kind','furniture');p=pts(o);lo=min(v.z for v in p);hi=max(v.z for v in p)
  if kind in ('furniture','ground_container') or (kind=='fixture' and lo<fz+1.2 and hi>fz+.35):
   h=hull(o)
   if h.intersects(domain):blockers.append(h.buffer(.25))
 free=domain.buffer(-.25).difference(unary_union(blockers))
 # Hollow shower tray interior is a physically standable surface; keep .27m from enclosure walls.
 free=free.union(shower_inside.intersection(domain.buffer(-.25)))
 nearby=[d for d in doors if d[1].distance(domain)<.1 and max(v.z for v in pts(d[0]))>fz+.8 and min(v.z for v in pts(d[0]))<fz+2]
 door_sections=[]
 for o,h,bvh in nearby:
  # Slice joined native door/frame mesh at torso height, rather than treating
  # the entire casing convex hull (including its empty opening) as solid.
  vertices=[o.matrix_world@v.co for v in o.data.vertices];segments=[];z=fz+.8
  for poly in o.data.polygons:
   corners=[vertices[i] for i in poly.vertices];cross=[]
   for j,u in enumerate(corners):
    w=corners[(j+1)%len(corners)]
    if (u.z-z)*(w.z-z)<0:
     t=(z-u.z)/(w.z-u.z);cross.append((u.x+t*(w.x-u.x),u.y+t*(w.y-u.y)))
   if len(cross)>=2:segments.append(LineString(cross).buffer(.25))
  section=unary_union(segments);door_sections.append(section);free=free.difference(section)
 targets=[center(item(key+s)) for s in ('_wc','_vanity','_shower')]
 for t in targets:t.z=fz+.9
 target=sum(targets,Vector())/3
 candidates=[];x0,y0,x1,y1=domain.bounds
 for x in np.arange(x0+.05,x1,.075):
  for y in np.arange(y0+.05,y1,.075):
   if not free.covers(Point(float(x),float(y))):continue
   eye=Vector((float(x),float(y),fz+1.55));visible=[]
   for t in targets:
    delta=t-eye;blocked=False
    for o,h,bvh in nearby:
     hit=bvh.ray_cast(eye,delta.normalized(),delta.length)
     if hit[0] is not None:blocked=True;break
    visible.append(not blocked)
   # All fixtures should fit within 95 degree horizontal field of view.
   forward=target-eye;forward.z=0;angles=[]
   for t in targets:
    d=t-eye;d.z=0;angles.append(forward.angle(d,0))
   fit=max(angles)<math.radians(45)
   score=100*sum(visible)+100*fit+(eye-target).length
   candidates.append((score,eye,visible,fit))
 assert candidates,(key,domain.bounds,shower_inside.bounds,free.area,[(o.name,h.bounds,h.area) for o,h,b in nearby])
 score,eye,visible,fit=max(candidates,key=lambda row:row[0])
 v=next(v for v in views if v['name']==key+'_wetroom_review');old=dict(v);v.update(name=key+'_wetroom_review_v2',location=list(eye),target=list(target),hfov=95)
 records.append({'domain_wkt':domain.wkt,'free_wkt':free.wkt,'door_sections_wkt':[q.wkt for q in door_sections],'fixtures':{k:hull(item(key+k)).wkt for k in ('_wc','_vanity','_shower')},'key':key,'old_rejected_pose':old,'replacement':v,'door_leaves':[o.name for o,h,b in nearby],'wc_vanity_shower_door_visibility':visible,'horizontal_fit':fit,'standing_clearance_radius_m':.25,'free_area_m2':free.area,'in_shower_interior':shower_inside.covers(Point(eye.x,eye.y)),'limitations':'Door mesh rays verify visibility; final rendered visual review still required. Shower interior uses enclosed tray footprint with .27m inset.'})
(base/f'review_views_delivery_r{revision}_provisional.json').write_text(json.dumps(views,indent=2));(ref/f'wetroom_camera_repair_r{revision}.json').write_text(json.dumps(records,indent=2));print(json.dumps(records),flush=True)
