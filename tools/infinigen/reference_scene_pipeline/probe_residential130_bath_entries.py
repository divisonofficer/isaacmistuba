import bpy,sys,json,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
R=Path('/jarvis/project/robomituba');sys.path.insert(0,str(R/'tools/infinigen/reference_scene_pipeline'))
from physical_scene_geometry import render_mesh_candidates,evaluated_surface
src=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r130_draft.blend';before=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));objects,_=render_mesh_candidates();regions=[(101,3.,3.,6.),(102,18.5,3.,6.)];rows=[]
for unit,x,y0,y1 in regions:
 candidates=[];details=[]
 for o in objects:
  # Conservative object box for broadphase, exact faced surface for evidence.
  pp=[o.matrix_world@Vector(v) for v in o.bound_box]
  if max(p.x for p in pp)<x-.65 or min(p.x for p in pp)>x+.65 or max(p.y for p in pp)<y0 or min(p.y for p in pp)>y1 or min(p.z for p in pp)>1.9:continue
  ps,fs,used=evaluated_surface(o)
  if not fs:continue
  lo=[min(ps[i][k] for i in used) for k in range(3)];hi=[max(ps[i][k] for i in used) for k in range(3)]
  tree=BVHTree.FromPolygons(ps,fs,all_triangles=True);candidates.append((o.name,tree));row={'object':o.name,'bbox_faced_vertices_m':[lo,hi],'triangles':len(fs),'program_key':str(o.get('program_key',''))}
  if 'Door' in o.name or 'door' in o.name:
   a=o.data.attributes.get('door_frame')
   if a and a.domain=='POINT':
    pts=[o.matrix_world@v.co for v,z in zip(o.data.vertices,a.data) if z.value and v.index in used]
    if pts:row['fixed_frame_world_bbox_m']=[[min(p[k] for p in pts) for k in range(3)],[max(p[k] for p in pts) for k in range(3)]]
  details.append(row)
 scans=[]
 for i in range(31):
  y=y0+i*.1
  for z in [.4145347,1.0145347,1.6145347]:
   origin=Vector((x-.65,y,z));direction=Vector((1,0,0));hits=[]
   for name,tree in candidates:
    loc,no,idx,dist=tree.ray_cast(origin,direction,1.3)
    if loc is not None:hits.append({'object':name,'xyz_m':list(loc),'distance_m':dist})
   scans.append({'y_m':y,'z_m':z,'cross_wall_segment_hits':sorted(hits,key=lambda h:h['distance_m'])})
 rows.append({'unit':unit,'wall_boundary_x_m':x,'objects':details,'scans':scans})
assert hashlib.sha256(src.read_bytes()).hexdigest()==before
out={'source':str(src),'source_sha256':before,'rows':rows,'scope':'Read-only actual evaluated all-render triangle ray probes across bathroom2 boundary, x +/-650mm, y every100mm and 3 body heights. Identifies obstruction candidates, not body clearance, door swing or architectural aperture certification.'}
p=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/bathroom2_130_entry_diagnosis.json';p.write_text(json.dumps(out,indent=2));print('BATH130_ENTRY_PROBE',[(r['unit'],len(r['objects'])) for r in rows],flush=True)
