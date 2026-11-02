"""Read-only initial cloth topology/self-overlap diagnostic; excludes neighbours and coincident seam vertices."""
import bpy,json,hashlib
from pathlib import Path
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[3];source=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r37.blend';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';bpy.ops.wm.open_mainfile(filepath=str(source));rows=[]
for pattern in range(6):
 o=next(o for o in bpy.data.objects if o.get('program_key')==f'101_native_garment_0_{pattern}');mesh=o.data;polys=[list(f.vertices) for f in mesh.polygons];tree=BVHTree.FromPolygons([v.co for v in mesh.vertices],polys);overlaps=tree.overlap(tree);sets=[set(f) for f in polys];coords=[{tuple(round(float(x),7) for x in mesh.vertices[i].co) for i in f} for f in polys];pairs=[]
 for i,j in overlaps:
  if j<=i or sets[i]&sets[j] or coords[i]&coords[j]:continue
  pairs.append([i,j])
 adjacency=[[] for _ in mesh.vertices]
 for e in mesh.edges:a,b=e.vertices;adjacency[a].append(b);adjacency[b].append(a)
 pending=set(range(len(mesh.vertices)));components=[]
 while pending:
  stack=[pending.pop()];count=0
  while stack:
   i=stack.pop();count+=1
   for j in adjacency[i]:
    if j in pending:pending.remove(j);stack.append(j)
  components.append(count)
 rows.append({'pattern':pattern,'object':o.name,'vertices':len(mesh.vertices),'faces':len(polys),'connected_vertex_components':components,'candidate_nonadjacent_self_overlap_pairs':len(pairs),'sample_pairs':pairs[:8],'zero_area_faces':sum(f.area<1e-12 for f in mesh.polygons)});print('INITIAL_STATE_PATTERN',pattern,rows[-1]['candidate_nonadjacent_self_overlap_pairs'],flush=True)
result={'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'gravity':list(bpy.context.scene.gravity),'external_cloth_colliders':[o.name for o in bpy.data.objects if any(m.type=='COLLISION' for m in o.modifiers)],'force_fields':[o.name for o in bpy.data.objects if o.field and o.field.type!='NONE'],'patterns':rows,'limitations':'BVH overlap candidates exclude shared indices/positions;not signed penetration depth and not photographic acceptance.'};(ref/'garment_initial_state_r37.json').write_text(json.dumps(result,indent=2))
