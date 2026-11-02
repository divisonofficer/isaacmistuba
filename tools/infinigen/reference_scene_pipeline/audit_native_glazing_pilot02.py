"""Read-only evaluated manufactured pane/frame topology audit, not visual acceptance."""
import bpy,json
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];D=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/native_fullheight_glazing_pilot02';assert not (D/'geometry_audit.json').exists();bpy.ops.wm.open_mainfile(filepath=str(D/'asset.blend'));o=bpy.data.objects['Office02_native_fullheight_glazing_pilot02'];ev=o.evaluated_get(bpy.context.evaluated_depsgraph_get());me=ev.to_mesh();glassids={i for i,m in enumerate(me.materials) if m and 'clear_dielectric' in m.name};faces=[f for f in me.polygons if f.material_index in glassids];assert faces
adj={};edges={}
for f in faces:
 vs=list(f.vertices)
 for i,a in enumerate(vs):
  b=vs[(i+1)%len(vs)];adj.setdefault(a,set()).add(b);adj.setdefault(b,set()).add(a);e=tuple(sorted((a,b)));edges[e]=edges.get(e,0)+1
remaining=set(adj);components=[]
while remaining:
 todo=[remaining.pop()];verts=set(todo)
 while todo:
  v=todo.pop()
  for q in adj[v]:
   if q in remaining:remaining.remove(q);verts.add(q);todo.append(q)
 pts=[o.matrix_world@me.vertices[i].co for i in verts];lo=[min(v[k] for v in pts) for k in range(3)];hi=[max(v[k] for v in pts) for k in range(3)];component_edges=[n for (a,b),n in edges.items() if a in verts and b in verts];components.append({'vertices':len(verts),'bounds_min':lo,'bounds_max':hi,'dimensions_m':[hi[k]-lo[k] for k in range(3)],'glass_edge_nonmanifold_count':sum(n!=2 for n in component_edges)})
report={'asset':'asset.blend','evaluated_faces':len(me.polygons),'raw_faces':len(o.data.polygons),'glass_components':components,'scope':'Actual evaluated glass material connected components and world bounds. Edge counts test pane closure only; no global BVH/volume, installation, glass optical compliance or photo acceptance.','all_glass_components_closed':all(c['glass_edge_nonmanifold_count']==0 for c in components),'all_panes_finite_thickness':all(c['dimensions_m'][1]>.001 for c in components),'photorealism_accepted':False};ev.to_mesh_clear();(D/'geometry_audit.json').write_text(json.dumps(report,indent=2)+'\n');print('GLAZING_AUDIT_WRITTEN',json.dumps(report),flush=True)
