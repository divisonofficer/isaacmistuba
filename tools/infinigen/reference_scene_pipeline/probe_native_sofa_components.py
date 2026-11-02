"""Native whole-sofa components and placement bounds for next source integration."""
import bpy,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=ref/'native_sofa_engine_prototype_01.blend';bpy.ops.wm.open_mainfile(filepath=str(src));o=bpy.data.objects['NativeSofaEngine_L_candidate'];m=o.data;adj=[[] for _ in m.vertices]
for edge in m.edges:a,b=edge.vertices;adj[a].append(b);adj[b].append(a)
pending=set(range(len(m.vertices)));rows=[]
while pending:
 stack=[pending.pop()];ids=[]
 while stack:
  i=stack.pop();ids.append(i)
  for j in adj[i]:
   if j in pending:pending.remove(j);stack.append(j)
 group=set(ids);points=[o.matrix_world@m.vertices[i].co for i in ids];rows.append({'component':len(rows),'vertices':len(ids),'faces':sum(f.vertices[0] in group for f in m.polygons),'world_bounds':[[min(p[k] for p in points) for k in range(3)],[max(p[k] for p in points) for k in range(3)]]})
(ref/'native_sofa_engine_component_inventory.json').write_text(json.dumps({'source':str(src),'object':o.name,'matrix_world':[list(r) for r in o.matrix_world],'dimensions':list(o.dimensions),'components':rows,'scope':'Native prototype geometry inventory,not a placement or material/physics/visual acceptance in the house'},indent=2));print('NATIVE_SOFA_COMPONENTS',len(rows),'dimensions',list(o.dimensions),flush=True)
