"""Saved native moving leaf/lever 41-angle surface-intersection test; not continuous certification."""
import bpy,json,hashlib,sys,math
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent))
from physical_scene_geometry import render_mesh_candidates,evaluated_surface
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';record=json.loads((D/'entry_batch133_build.json').read_text());src=Path(record['candidate']);sha=hashlib.sha256(src.read_bytes()).hexdigest();assert sha==record['candidate_sha256'];bpy.ops.wm.open_mainfile(filepath=str(src));bpy.context.view_layer.update();results=[]
for row in record['rows']:
 o=bpy.data.objects[row['new_object']];assert not o.modifiers;hinge=Vector(row['hinge_world_m']);moving={v.index for v in o.data.vertices if o.data.attributes['door_left'].data[v.index].value};o.data.calc_loop_triangles();world=[o.matrix_world@v.co for v in o.data.vertices];tri=[tuple(t.vertices) for t in o.data.loop_triangles];moving_tri=[f for f in tri if set(f)<=moving];assert moving_tri;assert all(not (set(f)&moving) or set(f)<=moving for f in tri);used={i for f in moving_tri for i in f};objects,_=render_mesh_candidates();obstacles=[]
 # Bounding envelope includes full0..90deg sweep; all render meshes admitted, no name exemptions.
 for q in objects:
  bb=[q.matrix_world@Vector(v) for v in q.bound_box]
  if max(p.x for p in bb)<hinge.x-1.3 or min(p.x for p in bb)>hinge.x+1.3 or max(p.y for p in bb)<hinge.y-1.3 or min(p.y for p in bb)>hinge.y+1.3 or min(p.z for p in bb)>2.43 or max(p.z for p in bb)<.1225:continue
  if q==o:
   ps=world;fs=[f for f in tri if not set(f)&moving]
  else:ps,fs,_=evaluated_surface(q)
  if fs:obstacles.append((q.name,BVHTree.FromPolygons(ps,fs,all_triangles=True)))
 rows=[]
 for step in range(41):
  degrees=-step*2.5;M=Matrix.Rotation(math.radians(degrees+100),4,'Z');ps=[hinge+M@(p-hinge) if i in used else p for i,p in enumerate(world)];tree=BVHTree.FromPolygons(ps,moving_tri,all_triangles=True);hits=[]
  for name,ob in obstacles:
   crossing=tree.overlap(ob)
   if crossing:hits.append({'object':name,'triangle_surface_crossings':len(crossing)})
  rows.append({'angle_deg':degrees,'intersections':hits})
 results.append({'role':row['role'],'moving_object':o.name,'angles':rows,'fixed_obstacle_meshes_tested':len(obstacles),'sampled_surface_intersections_clear':all(not x['intersections'] for x in rows)})
assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
out={'source':str(src),'source_sha256':sha,'rows':results,'sampled_surface_intersections_clear':all(x['sampled_surface_intersections_clear'] for x in results),'scope':'41 rigid native leaf+lever poses0..-100deg at2.5deg increments against ALL enabled render meshes in conservative bbox, plus own fixed frame. Exact loop-triangle surface intersections only; not continuous swept volume, containment, hardware force or accessibility certification. No obstacle name exemptions.','accepted':False}
(D/'entry133_sampled_sweeps.json').write_text(json.dumps(out,indent=2));print('ENTRY133_SWEEPS',out['sampled_surface_intersections_clear'],[(r['role'],[(x['angle_deg'],x['intersections']) for x in r['angles'] if x['intersections']]) for r in results],flush=True)
