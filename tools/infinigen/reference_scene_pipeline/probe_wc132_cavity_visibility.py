"""Read-only native-bowl vertical visibility probes; distinguish product shell from floor seen through it."""
import bpy,json,hashlib,sys
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent))
from physical_scene_geometry import render_mesh_candidates,evaluated_surface
from compact_wc_contract import mesh_geometry_hash
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r132_draft.blend';before=hashlib.sha256(src.read_bytes()).hexdigest();contract=json.loads((D/'native_fullsize_wc100/contract.json').read_text());centre=json.loads((D/'wc109_trap_inlet.json').read_text())['center_xy_m'];bpy.ops.wm.open_mainfile(filepath=str(src));objects,_=render_mesh_candidates();bodies=[o for o in objects if str(o.get('program_key','')).endswith('_wc')];assert len(bodies)==10;floors=[]
for o in objects:
 if o.name.endswith('.floor'):
  ps,fs,_=evaluated_surface(o)
  if fs:floors.append((o.name,BVHTree.FromPolygons(ps,fs,all_triangles=True)))
rows=[]
for o in bodies:
 same=mesh_geometry_hash(o.data)==contract['mesh_geometry_sha256'];row={'object':o.name,'program_key':o['program_key'],'raw_native_geometry_identical_to_product100':same,'scale':list(o.scale),'probes':[]}
 if same:
  ps,fs,_=evaluated_surface(o);tree=BVHTree.FromPolygons(ps,fs,all_triangles=True);M=o.matrix_world;inv=M.inverted();direction=(M.to_3x3()@Vector((0,0,-1))).normalized()
  for dx,dy in [(0,0),(-.025,0),(.025,0),(0,-.02),(0,.02),(-.05,0),(.05,0)]:
   origin=M@Vector((centre[0]+dx,centre[1]+dy,.70));hit,normal,face,dist=tree.ray_cast(origin,direction,1.);floorhits=[]
   for name,t in floors:
    p,n,i,dd=t.ray_cast(origin,direction,1.)
    if p is not None:floorhits.append((dd,name,list(p)))
   row['probes'].append({'native_xy_m':[centre[0]+dx,centre[1]+dy],'product_first_hit_native_z_m':(inv@hit).z if hit is not None else None,'product_first_face':face,'nearest_floor_hit':min(floorhits) if floorhits else None,'unobstructed_vertical_view_to_floor':hit is None and bool(floorhits)})
 rows.append(row)
assert hashlib.sha256(src.read_bytes()).hexdigest()==before
out={'source':str(src),'source_sha256':before,'native_product_contract_sha256':hashlib.sha256((D/'native_fullsize_wc100/contract.json').read_bytes()).hexdigest(),'rows':rows,'scope':'Seven vertical native-coordinate rays per hash-identical product at measured inlet XY, from z0.70m downward. Own product triangles and render-enabled .floor meshes separately. Not a pixel-level attribution, off-axis optical ray, fluid seal, collision, or full sanitary completeness certification. No scene changes.'}
(D/'wc132_cavity_visibility_probe.json').write_text(json.dumps(out,indent=2));print('WC132_CAVITY',[(r['program_key'],r['raw_native_geometry_identical_to_product100'],sum(p['unobstructed_vertical_view_to_floor'] for p in r['probes'])) for r in rows],flush=True)
