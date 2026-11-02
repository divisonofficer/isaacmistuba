import bpy,json
from pathlib import Path
r=Path('/jarvis/project/robomituba');bpy.ops.wm.open_mainfile(filepath=str(r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r70.blend'));bpy.context.view_layer.update();rows=[]
for o in bpy.data.objects:
 if o.type!='MESH' or 'DeskBenchFactory' not in o.name:continue
 adj={v.index:set() for v in o.data.vertices}
 for e in o.data.edges:a,b=e.vertices;adj[a].add(b);adj[b].add(a)
 unseen=set(adj);parts=[]
 while unseen:
  todo=[unseen.pop()];ids=set(todo)
  while todo:
   for i in adj[todo.pop()]:
    if i in unseen:unseen.remove(i);ids.add(i);todo.append(i)
  vs=[o.data.vertices[i].co for i in ids];world=[o.matrix_world@v for v in vs];parts.append({'n':len(ids),'local_bounds':[[min(v[k] for v in vs) for k in range(3)],[max(v[k] for v in vs) for k in range(3)]],'world_bounds':[[min(v[k] for v in world) for k in range(3)],[max(v[k] for v in world) for k in range(3)]],'materials':list(set(o.data.materials[p.material_index].name for p in o.data.polygons if p.vertices[0] in ids))})
 rows.append({'key':o['program_key'],'parts':parts})
p=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/bench_components_probe_r70.json';p.write_text(json.dumps(rows,indent=2));print(json.dumps(rows[0],indent=2))
