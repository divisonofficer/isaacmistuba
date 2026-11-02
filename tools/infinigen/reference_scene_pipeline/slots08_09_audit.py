"""Bounded saved-mesh floor contacts/fit; not exhaustive circulation or photo proof."""
import bpy,json,sys
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3];args=sys.argv[sys.argv.index('--')+1:];scene=args[0];rev=args[1] if len(args)>1 else 'r002';seed=48712509 if'duplex'in scene else 48712508;D=R/'data/venue_refs/floor_plans_v3'/scene;P=R/'out/infinigen_v2'/f'kr_{scene}_{seed}/full/scene_candidate_{rev}.blend';bpy.ops.wm.open_mainfile(filepath=str(P));bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();floors=[]
for o in bpy.context.scene.objects:
 if o.type=='MESH' and (o.name.endswith('.floor') or 'structural_floor'in o.name or 'structural_slab'in o.name or 'terrace_structural_plate'in o.name or o.name=='Stair_top_landing'):
  ev=o.evaluated_get(dg);m=ev.to_mesh();vs=[o.matrix_world@v.co for v in m.vertices];tree=BVHTree.FromPolygons(vs,[list(f.vertices) for f in m.polygons]);floors.append((o.name,tree,min(v.z for v in vs),max(v.z for v in vs)));ev.to_mesh_clear()
rows=[]
for o in bpy.context.scene.objects:
 if o.type!='MESH' or not(o.get('native_product_id') or o.get('unit_scale_preserved')):continue
 vs=[o.matrix_world@v.co for v in o.data.vertices];lo=Vector([min(v[k] for v in vs) for k in range(3)]);hi=Vector([max(v[k] for v in vs) for k in range(3)]);feet=[p for p in vs if p.z<=lo.z+.00002];probes=[]
 for p in feet[:100]:
  hits=[]
  for name,tree,z0,z1 in floors:
   hit,normal,face,dist=tree.ray_cast(p+Vector((0,0,.4)),Vector((0,0,-1)),5)
   if hit is not None:hits.append((abs(p.z-hit.z),p.z-hit.z,name))
  probes.append(min(hits) if hits else None)
 contact=bool(probes) and all(x is not None and abs(x[1])<.015 for x in probes)
 rows.append({'object':o.name,'asset_id':o.get('native_product_id'),'bounds_xyz_m':[list(lo),list(hi)],'lowest_vertex_floor_probes':probes,'lowest_vertices_contact_within15mm':contact,'scope':'Lowest vertices per mesh; elevated native component pieces are not expected to contact floor independently. Not all-leg load or route proof.'})
result={'source':str(P),'floors':[{'object':n,'bottom_z':z0,'top_z':z1} for n,t,z0,z1 in floors],'mesh_lowest_vertex_probes':rows,'acceptance':False,'scope':'Saved evaluated floor triangles and actual native source vertices only. Per-mesh floating flags include multi-piece assembly subparts;group review needed. Door sweeps/full circulation/guard engineering not certified.'};(D/f'physical_audit_{rev}.json').write_text(json.dumps(result,indent=2));print('PHYSICAL_AUDIT_SAVED',scene,len(rows),[(n,z0,z1)for n,t,z0,z1 in floors],flush=True)
