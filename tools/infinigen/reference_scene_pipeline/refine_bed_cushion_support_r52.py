"""Rigid teal bed-cushion pose repair inside the original mesh;UV/material/modifiers retained."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r51.blend';out=base/'scene_candidate_r52.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
def eval_mesh(o):
 bpy.context.view_layer.update();ev=o.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=ev.to_mesh();v=[o.matrix_local@p.co for p in mesh.vertices];f=[list(p.vertices) for p in mesh.polygons];ev.to_mesh_clear();return v,f
for unit in [101,102]:
 key=f'{unit}_bedroom2_bed';bed=next(o for o in bpy.data.objects if o.get('program_key')==key);bed.data=bed.data.copy();bpy.context.view_layer.update();ev=bed.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=ev.to_mesh();pv=[v.co.copy() for v in mesh.vertices];whitefaces=[list(f.vertices) for f in mesh.polygons if mesh.materials[f.material_index].name.startswith(('ir_sfb_white','ir_sfb_greige')) and f.normal.x>.05];assert whitefaces;back=BVHTree.FromPolygons(pv,whitefaces);whitepoints=[pv[i] for i in {i for f in whitefaces for i in f}];components=[]
 for sign in [-1,1]:
  faces=[list(f.vertices) for f in mesh.polygons if mesh.materials[f.material_index].name.startswith('ir_sfb_petrol') and sign*f.center.y>0];assert faces;ids=sorted({i for f in faces for i in f});lookup={old:i for i,old in enumerate(ids)};components.append((sign,[pv[i] for i in ids],[[lookup[i] for i in f] for f in faces]))
 ev.to_mesh_clear();support_points=[];support_faces=[]
 for suffix in ['_closed_mattress','_draped_duvet']:
  obj=next(o for o in bpy.data.objects if o.get('program_key')==key+suffix);v,f=eval_mesh(obj);offset=len(support_points);support_points.extend(v);support_faces.extend([[i+offset for i in face] for face in f])
 support=BVHTree.FromPolygons(support_points,support_faces)
 for sign,points,faces in components:
  dx=dz=0;original_gaps=[]
  for q in points:
   hit,_,_,_=support.ray_cast(Vector((q.x,q.y,3)),Vector((0,0,-1)),4)
   if hit is not None:original_gaps.append(q.z-hit.z)
  def required_x(z):
   values=[]
   for q in points:
    hit,_,_,_=back.ray_cast(Vector((3,q.y,q.z+z)),Vector((-1,0,0)),4)
    if hit is not None:values.append(hit.x-q.x+.0005)
   assert values;return max(values)
  for iteration in range(8):
   values=[]
   for q in points:
    hit,_,_,_=support.ray_cast(Vector((q.x+dx,q.y,3)),Vector((0,0,-1)),4)
    if hit is not None:values.append(hit.z-q.z+.0005)
   assert values;dz=max(values);dx=required_x(dz)
  # Exact triangle overlap catches support-height jumps between sampled cushion vertices.
  clearance=0
  for iteration in range(31):
   placed=[v+Vector((dx,0,dz)) for v in points];body=BVHTree.FromPolygons(placed,faces);overlap={'support':len(body.overlap(support)),'white_pillow_front':len(body.overlap(back))}
   if not any(overlap.values()):break
   if overlap['support']:dz+=.001;clearance+=.001;dx=required_x(dz)
   if overlap['white_pillow_front']:dx+=.001
  assert not any(overlap.values()),(key,sign,overlap);gap={'support':min(min(support.find_nearest(q)[3] for q in placed),min(body.find_nearest(q)[3] for q in support_points)),'white_back':min(min(back.find_nearest(q)[3] for q in placed),min(body.find_nearest(q)[3] for q in whitepoints))};assert max(gap.values())<.003,(key,sign,gap);assert abs(dx)<.15 and -.12<dz<.02,(dx,dz);basefaces=[f for f in bed.data.polygons if bed.data.materials[f.material_index].name.startswith('ir_sfb_petrol') and sign*f.center.y>0];ids={i for f in basefaces for i in f.vertices};delta=Vector((dx,0,dz))
  for i in ids:bed.data.vertices[i].co+=delta
  rows.append({'bed':key,'side_sign':sign,'translation_m':list(delta),'minimum_original_vertical_gap_m':min(original_gaps),'minimum_bidirectional_vertex_surface_gap_m':gap,'triangle_surface_overlap_pairs':overlap,'extra_surface_clearance_m':clearance,'moved_base_vertices':len(ids),'scope':'rigid pose only;original mesh UV,materials,modifiers retained. White-white pillow overlap andpadding volume remain separate.'})
 bed.data.update()
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r52.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'scope':'four bedroom2 teal cushions moved rigidly insideoriginal bed mesh;all cloth,other bed parts,UV/materials/modifiers andlighting unchanged. Evaluated original modifier geometry used forfit.','cushions':rows,'photorealism_accepted':False,'requires':'same front/reverse actual images;volume/compression/white pillows andbedding construction unresolved'},indent=2));print('SAVED',out,flush=True)
