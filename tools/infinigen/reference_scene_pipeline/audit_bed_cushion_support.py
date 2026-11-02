"""Read-only saved-file evaluated support check;optional source comparison proves rigid edit scope."""
import bpy,json,hashlib,argparse
import numpy as np
from pathlib import Path
from mathutils.bvhtree import BVHTree
p=argparse.ArgumentParser();p.add_argument('--blend',type=Path,required=True);p.add_argument('--source',type=Path);p.add_argument('--out',type=Path,required=True);a=p.parse_args();baseline={};rows=[];errors=[]
def beds():return [o for o in bpy.data.objects if o.get('program_key') in ['101_bedroom2_bed','102_bedroom2_bed']]
def snapshot(o):
 mask=np.zeros(len(o.data.vertices),dtype=bool)
 for f in o.data.polygons:
  if o.data.materials[f.material_index].name.startswith('ir_sfb_petrol'):mask[list(f.vertices)]=True
 co=np.array([list(v.co) for v in o.data.vertices],dtype=np.float32);uv=[(x.name,hashlib.sha256(np.array([list(y.uv) for y in x.data],dtype=np.float32).tobytes()).hexdigest()) for x in o.data.uv_layers];return {'outside_cyan_hash':hashlib.sha256(co[~mask].tobytes()).hexdigest(),'UV':uv,'topology':hashlib.sha256(str([list(f.vertices) for f in o.data.polygons]).encode()).hexdigest(),'material_slots':[m.name for m in o.data.materials],'pose':[list(r) for r in o.matrix_world]}
if a.source:
 bpy.ops.wm.open_mainfile(filepath=str(a.source.resolve()));baseline={o['program_key']:snapshot(o) for o in beds()}
bpy.ops.wm.open_mainfile(filepath=str(a.blend.resolve()));bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get()
for bed in beds():
 key=bed['program_key'];scope=snapshot(bed)==baseline[key] if baseline else None
 if scope is False:errors.append({'bed':key,'reason':'UV_topology_pose_or_noncyan_geometry_changed'})
 ev=bed.evaluated_get(deps);m=ev.to_mesh();points=[v.co.copy() for v in m.vertices];white=[list(f.vertices) for f in m.polygons if m.materials[f.material_index].name.startswith(('ir_sfb_white','ir_sfb_greige')) and f.normal.x>.05];back=BVHTree.FromPolygons(points,white);whitepoints=[points[i] for i in {i for f in white for i in f}];bodies=[]
 for sign in [-1,1]:
  faces=[list(f.vertices) for f in m.polygons if m.materials[f.material_index].name.startswith('ir_sfb_petrol') and sign*f.center.y>0];assert faces;ids={i for f in faces for i in f};bodies.append((sign,BVHTree.FromPolygons(points,faces),[points[i] for i in ids]))
 ev.to_mesh_clear();sv=[];sf=[]
 for suffix in ['_closed_mattress','_draped_duvet']:
  o=next(o for o in bpy.data.objects if o.get('program_key')==key+suffix);ev=o.evaluated_get(deps);m=ev.to_mesh();off=len(sv);sv.extend([o.matrix_local@v.co for v in m.vertices]);sf.extend([[i+off for i in f.vertices] for f in m.polygons]);ev.to_mesh_clear()
 support=BVHTree.FromPolygons(sv,sf)
 for sign,body,bv in bodies:
  overlaps={'support':len(body.overlap(support)),'white_back':len(body.overlap(back))};gaps={'support':min(min(support.find_nearest(q)[3] for q in bv),min(body.find_nearest(q)[3] for q in sv)),'white_back':min(min(back.find_nearest(q)[3] for q in bv),min(body.find_nearest(q)[3] for q in whitepoints))};good=not any(overlaps.values()) and max(gaps.values())<.003;rows.append({'bed':key,'side_sign':sign,'actual_saved_evaluated_overlap_pairs':overlaps,'minimum_bidirectional_vertex_surface_gap_m':gaps,'source_scope_unchanged':scope,'pass':good})
  if not good:errors.append({'bed':key,'side':sign,'overlaps':overlaps,'gaps':gaps})
assert len(rows)==4;result={'source':str(a.blend.resolve()),'source_sha256':hashlib.sha256(a.blend.read_bytes()).hexdigest(),'comparison_source':str(a.source) if a.source else None,'cushions':rows,'errors':errors,'status':'scoped_saved_cushion_support_pass' if not errors else 'repair_required','photorealism_accepted':False,'scope':'Actual saved evaluated4teal cushions vs mattress/duvet andwhite front surfaces;not white-white collision,soft compression or whole scene navigation.'};a.out.write_text(json.dumps(result,indent=2));print(json.dumps({'checked':len(rows),'errors':errors}),flush=True)

if errors:raise SystemExit(1)
