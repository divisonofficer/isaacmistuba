"""Saved evaluated wall clearance and sampled physical frame coverage."""
import bpy,json
from pathlib import Path
from mathutils import Matrix,Vector
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';a=json.loads((d/'glazing114_build.json').read_text());bpy.ops.wm.open_mainfile(filepath=a['candidate']);dg=bpy.context.evaluated_depsgraph_get();rows=[]
def tree(o):
 eo=o.evaluated_get(dg);me=eo.to_mesh();result=BVHTree.FromPolygons([eo.matrix_world@v.co for v in me.vertices],[list(f.vertices) for f in me.polygons]);eo.to_mesh_clear();return result
for row in a['rooms']:
 pose=Matrix(row['pose']);normal=pose.to_3x3()@Vector((0,1,0));walls=[(x['object'],tree(bpy.data.objects[x['object']])) for x in row['cuts']];frame=tree(bpy.data.objects[row['object']]);occluded=[];uncovered=[]
 for x in [-.9,-.5,.5,.9]:
  for z in [.15,1.1,2.25]:
   start=pose@Vector((x,-.5,z))
   for name,t in walls:
    hit=t.ray_cast(start,normal,1)[0]
    if hit is not None:occluded.append({'wall':name,'local':[x,z],'hit':list(hit)})
 border=[(x,.03+(2.335*i/6)) for x in [-1.045,1.045] for i in range(7)]+[(-1.04+2.08*i/8,z) for z in [.0275,2.3675] for i in range(9)]
 for x,z in border:
  start=pose@Vector((x,-.5,z));hit=frame.ray_cast(start,normal,1)[0]
  if hit is None:uncovered.append([x,z])
 rows.append({'room':row['room'],'evaluated_wall_ray_samples':48,'evaluated_wall_hits':occluded,'frame_perimeter_samples':len(border),'frame_uncovered_samples':uncovered})
out={'source':a['candidate'],'rooms':rows,'evaluated_clear_pane_samples_clear':all(not x['evaluated_wall_hits'] for x in rows),'sampled_frame_border_covered':all(not x['frame_uncovered_samples'] for x in rows),'scope':'Saved evaluated modifier geometry: 288 clear-pane wall rays and192 near-aperture border rays. Point samples do not prove all seam continuity, seals or structural mounting. RGB/navigation still pending.','accepted':False};(d/'glazing114_evaluated_fit_audit.json').write_text(json.dumps(out,indent=2));print('GLAZING114_EVALUATED_FIT',out['evaluated_clear_pane_samples_clear'],out['sampled_frame_border_covered']);assert out['evaluated_clear_pane_samples_clear'] and out['sampled_frame_border_covered']
