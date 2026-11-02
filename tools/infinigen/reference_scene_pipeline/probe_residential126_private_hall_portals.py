"""Actual all-render-mesh vertical/plan ray bands across the living/private-hall interface."""
import bpy,json,sys,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from physical_scene_geometry import render_mesh_candidates,evaluated_surface
src=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r126_draft.blend';d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';bpy.ops.wm.open_mainfile(filepath=str(src));objects,_=render_mesh_candidates();rows=[]
for unit in [101,102]:
 xlo,xhi=(4.8,7.2) if unit==101 else (14.3,16.7);trees=[]
 for o in objects:
  p=[o.matrix_world@Vector(v) for v in o.bound_box];lo=[min(v[k] for v in p) for k in range(3)];hi=[max(v[k] for v in p) for k in range(3)]
  if hi[0]<xlo or lo[0]>xhi or hi[1]<9.10 or lo[1]>9.9 or hi[2]<.13 or lo[2]>1.9:continue
  p,f,u=evaluated_surface(o);trees.append((o.name,BVHTree.FromPolygons(p,f,all_triangles=True)))
 for z in [.14,.19,.5,1.2,1.84]:
  samples=[]
  for i in range(97):
   x=xlo+i*.025;hits=[]
   for name,t in trees:
    p,n,face,dist=t.ray_cast(Vector((x,9.10,z)),Vector((0,1,0)),.8)
    if p is not None:hits.append({'object':name,'hit_xyz_m':list(p),'distance_m':dist})
   samples.append({'x_m':x,'clear':not hits,'nearest_hit':min(hits,key=lambda h:h['distance_m']) if hits else None})
  runs=[];start=None
  for s in samples+[{'clear':False}]:
   if s['clear'] and start is None:start=s['x_m']
   elif not s['clear'] and start is not None:runs.append([start,last]);start=None
   if s['clear']:last=s['x_m']
  rows.append({'unit':unit,'z_m':z,'clear_intervals_x_m':runs,'tested_objects':[n for n,t in trees],'samples':samples});print('PRIVATE126_PORTAL',unit,z,runs,sorted({s['nearest_hit']['object'] for s in samples if s['nearest_hit']}),flush=True)
(d/'private_hall126_ray_bands.json').write_text(json.dumps({'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'rows':rows,'scope':'Point rays every25mm at five absolute heights,97 x samples across each interface. Not a continuous600mm swept body/floor/door-motion test; rays may start in a solid. All enabled render meshes broadphase, actual evaluated triangles. No nav acceptance.','accepted':False},indent=2))
