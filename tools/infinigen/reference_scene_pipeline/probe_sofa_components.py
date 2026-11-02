"""Identify exact duplicate/contained back blocks behind the black image region."""
import bpy,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];source=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r46.blend';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';bpy.ops.wm.open_mainfile(filepath=str(source));rows=[]
for unit in [101,102]:
 o=next(o for o in bpy.data.objects if o.get('program_key')==f'{unit}_living_sectional');m=o.data;adj=[[] for _ in m.vertices]
 for e in m.edges:a,b=e.vertices;adj[a].append(b);adj[b].append(a)
 pending=set(range(len(m.vertices)));parts=[]
 while pending:
  stack=[pending.pop()];ids=[]
  while stack:
   i=stack.pop();ids.append(i)
   for j in adj[i]:
    if j in pending:pending.remove(j);stack.append(j)
  group=set(ids);faces=[f for f in m.polygons if f.vertices[0] in group];points=[m.vertices[i].co for i in ids];parts.append({'component':len(parts),'vertices':len(ids),'faces':len(faces),'bounds':[[min(p[k] for p in points) for k in range(3)],[max(p[k] for p in points) for k in range(3)]],'materials':sorted({m.materials[f.material_index].name for f in faces}),'smooth_faces':sum(f.use_smooth for f in faces)})
 rows.append({'unit':unit,'object':o.name,'components':parts,'modifiers':[{'name':n.name,'type':n.type} for n in o.modifiers]})
(ref/'sofa_component_probe_r46.json').write_text(json.dumps({'source':str(source),'objects':rows},indent=2));print(json.dumps(rows,indent=2))
