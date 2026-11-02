"""Bounded actual wall opening/door ray diagnosis, not a body navigation certificate."""
import bpy,json,sys
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from physical_scene_geometry import render_mesh_candidates,evaluated_surface
D=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r128_draft.blend';bpy.ops.wm.open_mainfile(filepath=str(src));physical,_=render_mesh_candidates();result=[]
for unit,x in [(101,5.),(102,16.5)]:
 local=[]
 for o in physical:
  ps=[o.matrix_world@Vector(v) for v in o.bound_box];lo=[min(v[k] for v in ps) for k in range(3)];hi=[max(v[k] for v in ps) for k in range(3)]
  if hi[0]<x-.65 or lo[0]>x+.65 or hi[1]<9.5 or lo[1]>12 or hi[2]<.13 or lo[2]>1.95:continue
  vs,fs,u=evaluated_surface(o);local.append((o.name,BVHTree.FromPolygons(vs,fs,all_triangles=True)))
 bands=[]
 for z in [.15,.19,.5,1.2,1.85]:
  samples=[]
  for j in range(251):
   y=9.5+j*.01;hits=[]
   for name,t in local:
    hit,n,idx,dist=t.ray_cast(Vector((x-.65,y,z)),Vector((1,0,0)),1.3)
    if hit is not None:hits.append({'object':name,'x':hit.x})
   samples.append({'y_m':y,'blockers':hits})
  bands.append({'z_m':z,'clear_y_samples_m':[s['y_m'] for s in samples if not s['blockers']],'samples':samples})
 result.append({'unit':unit,'boundary_x_m':x,'local_objects':[n for n,t in local],'bands':bands})
(D/'bedroom2_128_aperture_rays.json').write_text(json.dumps({'source':str(src),'units':result,'accepted':False,'scope':'All enabled render mesh objects in local bbox, evaluated surface horizontal rays at10mm Y pitch across1.3m centred architectural boundary x5/16.5,5heights. Point rays diagnose actual wall/casing/door blockers, not600mm footprint/continuous path/dynamic-door/whole navigation proof.'},indent=2));print('BEDROOM2_APERTURES',[(u['unit'],[(b['z_m'],min(b['clear_y_samples_m']) if b['clear_y_samples_m'] else None,max(b['clear_y_samples_m']) if b['clear_y_samples_m'] else None) for b in u['bands']]) for u in result],flush=True)
