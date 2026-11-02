"""Read-only native WC connected-component/manifold inventory for targeted repair."""
import bpy,json
from pathlib import Path
from collections import defaultdict,Counter
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=d/'native_fullsize_wc100/product.blend';bpy.ops.wm.open_mainfile(filepath=str(src));o=bpy.data.objects['NativeFullTankWC100'];me=o.data;n=len(me.vertices);parent=list(range(n))
def find(x):
 while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
 return x
def union(x,y):
 a,b=find(x),find(y)
 if a!=b:parent[b]=a
for e in me.edges:union(*e.vertices)
groups=defaultdict(list)
for v in me.vertices:groups[find(v.index)].append(v.index)
faces=defaultdict(list)
for f in me.polygons:faces[find(f.vertices[0])].append(f)
rows=[]
for root,ids in sorted(groups.items(),key=lambda x:len(x[1]),reverse=True):
 fs=faces[root];ec=Counter()
 for f in fs:
  vs=list(f.vertices)
  for a,b in zip(vs,vs[1:]+vs[:1]):ec[tuple(sorted((a,b)))]+=1
 points=[me.vertices[i].co for i in ids];lo=[min(v[k] for v in points) for k in range(3)];hi=[max(v[k] for v in points) for k in range(3)]
 rows.append({'component_index':len(rows),'vertices':len(ids),'faces':len(fs),'min':lo,'max':hi,'boundary_edges':sum(v==1 for v in ec.values()),'nonmanifold_edges':sum(v!=2 for v in ec.values()),'material_indices':sorted(set(f.material_index for f in fs)),'seed_vertex':ids[0]})
(d/'wc109_component_probe.json').write_text(json.dumps({'source':str(src),'object':o.name,'coordinate_space':'native local','components':rows,'scope':'Read-only connected face topology inventory. Component function is not inferred from bounds alone.'},indent=2));print(json.dumps(rows[:12],indent=2))
