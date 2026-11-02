"""Read-only audit of actual saved native bed-pillow assemblies,all eight bodies."""
import bpy,json,argparse,hashlib
from pathlib import Path
from mathutils.bvhtree import BVHTree
p=argparse.ArgumentParser();p.add_argument('--blend',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bpy.ops.wm.open_mainfile(filepath=str(a.blend.resolve()));bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();rows=[];pairs=[];errors=[]
def combined(objects,bed,front=False):
 points=[];faces=[]
 for o in objects:
  ev=o.evaluated_get(deps);mesh=ev.to_mesh();offset=len(points);M=bed.matrix_world.inverted()@o.matrix_world;points.extend([M@v.co for v in mesh.vertices]);faces.extend([[i+offset for i in f.vertices] for f in mesh.polygons if not front or f.normal.x>.05]);ev.to_mesh_clear()
 return BVHTree.FromPolygons(points,faces),points
for unit in [101,102]:
 bed=next(o for o in bpy.data.objects if o.get('program_key')==f'{unit}_bedroom2_bed');white=[o for o in bpy.data.objects if o.get('bed_pillow_unit')==unit and o.get('bed_pillow_kind')=='white'];teal=[o for o in bpy.data.objects if o.get('bed_pillow_unit')==unit and o.get('bed_pillow_kind')=='teal'];assert len(white)==len(teal)==2;support,sp=combined([next(o for o in bpy.data.objects if o.get('program_key')==f'{unit}_bedroom2_bed'+suffix) for suffix in ['_closed_mattress','_draped_duvet']],bed);head,hp=combined([bed],bed,True);whiteback,wp=combined(white,bed);bodies=[]
 for o in white+teal:
  body,bv=combined([o],bed);back,bp=(head,hp) if o in white else (whiteback,wp);overlap={'support':len(body.overlap(support)),'back':len(body.overlap(back))};gaps={'support':min(min(support.find_nearest(q)[3] for q in bv),min(body.find_nearest(q)[3] for q in sp)),'back':min(min(back.find_nearest(q)[3] for q in bv),min(body.find_nearest(q)[3] for q in bp))};ev=o.evaluated_get(deps);mesh=ev.to_mesh();edges={}
  for f in mesh.polygons:
   for edge in f.edge_keys:edges[edge]=edges.get(edge,0)+1
  nonmanifold=sum(n!=2 for n in edges.values());smooth=sum(f.use_smooth for f in mesh.polygons);closed=nonmanifold==0;good=closed and not any(overlap.values()) and max(gaps.values())<.003 and smooth==len(mesh.polygons);rows.append({'object':o.name,'unit':unit,'kind':o['bed_pillow_kind'],'surface_overlaps':overlap,'minimum_bidirectional_vertex_surface_gap_m':gaps,'nonmanifold_edges':nonmanifold,'actual_smooth_faces':smooth,'faces':len(mesh.polygons),'pass':good});ev.to_mesh_clear();bodies.append((o,body))
  if not good:errors.append(rows[-1])
 for i,(o,body) in enumerate(bodies):
  for other,t in bodies[i+1:]:
   count=len(body.overlap(t));pairs.append({'a':o.name,'b':other.name,'triangle_surface_overlaps':count})
   if count:errors.append(pairs[-1])
assert len(rows)==8;result={'source':str(a.blend.resolve()),'source_sha256':hashlib.sha256(a.blend.read_bytes()).hexdigest(),'auditor_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'pillows':rows,'pairwise':pairs,'errors':errors,'status':'scoped_native_bed_pillow_geometry_pass' if not errors else 'repair_required','photorealism_accepted':False,'scope':'Actual saved evaluated8native pillows:closure,smooth flags,pairwise/support/head or white-back triangle intersections andbidirectional vertex gaps. Not visual compression or whole-scene collision/navigation.'};a.out.write_text(json.dumps(result,indent=2));print(json.dumps({'pillows':len(rows),'pairs':len(pairs),'errors':errors}),flush=True)
if errors:raise SystemExit(1)
