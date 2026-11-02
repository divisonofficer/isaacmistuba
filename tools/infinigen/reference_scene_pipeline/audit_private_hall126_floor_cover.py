"""Exact local floor support under two body footprints, no name-based support proxy."""
import bpy,json,hashlib,sys
from pathlib import Path
from mathutils import Vector
from shapely.geometry import Polygon,LineString,box
from shapely.ops import unary_union
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from physical_scene_geometry import render_mesh_candidates,evaluated_surface
src=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r126_draft.blend';d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';bpy.ops.wm.open_mainfile(filepath=str(src));objects,_=render_mesh_candidates();fz=.1145347;rows=[]
for unit,x in [(101,5.95),(102,15.55)]:
 route=LineString([(x,9.0),(x,10.0)]).buffer(.3,resolution=48);region=box(*route.bounds);x0,y0,x1,y1=route.bounds;polys=[];tested=[]
 for o in objects:
  p=[o.matrix_world@Vector(v) for v in o.bound_box];lo=[min(v[k] for v in p) for k in range(3)];hi=[max(v[k] for v in p) for k in range(3)]
  if hi[0]<x0 or lo[0]>x1 or hi[1]<y0 or lo[1]>y1 or hi[2]<fz-.003 or lo[2]>fz+.003:continue
  p,f,u=evaluated_surface(o);count=0
  for ids in f:
   ps=[p[i] for i in ids]
   if min(v.z for v in ps)<fz-.003 or max(v.z for v in ps)>fz+.003:continue
   n=(ps[1]-ps[0]).cross(ps[2]-ps[0]);length=n.length
   if length<1e-12 or n.z/length<.98:continue
   shape=Polygon([(v.x,v.y) for v in ps]).intersection(region)
   if shape.area>1e-12:polys.append(shape);count+=1
  tested.append({'object':o.name,'actual_upward_triangles_covering_region':count})
 cover=unary_union(polys);missing=route.difference(cover);rows.append({'unit':unit,'route_centres_xy_m':[(x,9.0),(x,10.0)],'route_width_m':.6,'uncovered_area_m2':missing.area,'uncovered_bounds_xy_m':list(missing.bounds) if not missing.is_empty else None,'missing_geojson':missing.__geo_interface__,'exact_cover':cover.covers(route),'within_0_01mm_numeric_seams':cover.buffer(.00001).covers(route),'tested_all_render_support_candidates':tested});print('PRIVATE126_FULLWIDTH_FLOOR',unit,missing.area,list(missing.bounds),[(t['object'],t['actual_upward_triangles_covering_region']) for t in tested if t['actual_upward_triangles_covering_region']],flush=True)
(d/'private_hall126_floor_cover.json').write_text(json.dumps({'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'finish_z_m':fz,'rows':rows,'scope':'All enabled render meshes broadphase then actual evaluated upward world triangles within3mm finish, clipped to each complete600mm route footprint. No object-name floor whitelist or bbox support; positive support is an actual surface, not structural certification. Separate collision/door motion/global routes and other floor heights unverified.','accepted':False},indent=2))
