"""Static600mm body prisms at well-defined native frame centers; counterexamples only."""
import bpy,json,hashlib,sys
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from shapely.geometry import LineString,Point
from shapely.ops import triangulate
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from physical_scene_geometry import render_mesh_candidates,evaluated_surface
src=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r125_draft.blend';d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';inventory=json.loads((d/'door_frames125_inventory.json').read_text());assert hashlib.sha256(src.read_bytes()).hexdigest()==inventory['source_sha256'];bpy.ops.wm.open_mainfile(filepath=str(src));physical,_=render_mesh_candidates();boxes={}
for o in physical:
 p=[o.matrix_world@Vector(v) for v in o.bound_box];boxes[o.name]=[[min(v[k] for v in p) for k in range(3)],[max(v[k] for v in p) for k in range(3)]]
cache={};rows=[];excluded=[];low=.1145347+.02;high=low+1.75
for entry in inventory['doors']:
 lo,hi=entry['frame_bbox_m'];axis=entry['frame_normal_axis'];tangent=entry['frame_tangent_axis'];width=hi[tangent]-lo[tangent];depth=hi[axis]-lo[axis]
 if lo[2]>.2 or not .75<width<1.2 or depth>.15:
  excluded.append({'object':entry['object'],'frame_width_m':width,'frame_depth_m':depth,'frame_floor_z_m':lo[2],'reason':'Upper level, anomalous frame attribute extents, or non-axis-aligned frame: requires separate actual opening diagnosis.'});continue
 centre=entry['frame_center_m'][:2];points=[]
 for delta in [-.65,.65]:p=centre.copy();p[axis]+=delta;points.append(p)
 shape=LineString(points).buffer(.3,resolution=24);vertices=[];faces=[];lookup={}
 def ix(x,y,z):
  key=(round(x,9),round(y,9),z)
  if key not in lookup:lookup[key]=len(vertices);vertices.append(Vector((x,y,z)))
  return lookup[key]
 for t in triangulate(shape):
  if shape.covers(t):
   xy=list(t.exterior.coords)[:-1];faces.extend([tuple(ix(x,y,low) for x,y in xy),tuple(reversed([ix(x,y,high) for x,y in xy]))])
 boundary=list(shape.exterior.coords)[:-1]
 for (x,y),(xx,yy) in zip(boundary,boundary[1:]+boundary[:1]):faces.append((ix(x,y,low),ix(xx,yy,low),ix(xx,yy,high),ix(x,y,high)))
 tree=BVHTree.FromPolygons(vertices,faces);x0,y0,x1,y1=shape.bounds;collisions=[];tested=0
 for o in physical:
  a,b=boxes[o.name]
  if b[0]<x0 or a[0]>x1 or b[1]<y0 or a[1]>y1 or b[2]<low or a[2]>high:continue
  if o.name not in cache:
   p,f,u=evaluated_surface(o);cache[o.name]=(p,f,u,BVHTree.FromPolygons(p,f,all_triangles=True))
  p,f,u,t=cache[o.name];hits=tree.overlap(t);inside=[i for i in u if low+1e-5<p[i].z<high-1e-5 and x0<p[i].x<x1 and y0<p[i].y<y1 and shape.contains(Point(p[i].x,p[i].y))];tested+=1
  if hits or inside:
   zs=[p[i].z for aa,bb in hits for i in f[bb]];collisions.append({'object':o.name,'current_door_assembly':o.name==entry['object'],'surface_crossings':len(hits),'faced_vertices_inside_prism':len(inside),'crossing_triangle_z_range_m':[min(zs),max(zs)] if zs else None,'triangle_examples':[[list(p[i]) for i in f[bb]] for aa,bb in hits[:3]],'program_key':o.get('program_key')})
 rows.append({'door':entry['object'],'frame_center_xy_m':centre,'normal_axis':axis,'frame_outer_width_m':width,'route_centres_xy_m':points,'tested_objects':tested,'collisions':collisions,'surface_screen_clear':not collisions});print('PORTAL125_SCREEN',entry['object'],[(c['object'],c['surface_crossings']) for c in collisions],flush=True)
result={'source':str(src),'source_sha256':inventory['source_sha256'],'body_width_m':.6,'body_z_bounds_m':[low,high],'rows':rows,'excluded_frames':excluded,'scope':'Counterexample screen at actual native outer-frame centers in current static door poses. All enabled render objects considered; actual evaluated triangles and enclosed faced vertices. Center path may require a different approach or opening a movable leaf. No floor support, full containment, usable opening inference for excluded malformed attrs, door sweep, code compliance or whole-floor navigation certification.','accepted':False};(d/'portals125_surface_screen.json').write_text(json.dumps(result,indent=2));print('PORTAL125_SCREEN_COMPLETE',len(rows),len(excluded))
