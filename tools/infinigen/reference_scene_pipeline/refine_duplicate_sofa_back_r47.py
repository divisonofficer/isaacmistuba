"""Remove fully contained duplicate back block; keep outer dimensions and all other parts."""
import bpy,bmesh,json,hashlib
from pathlib import Path
from shapely.geometry import Polygon
from shapely.ops import unary_union
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r46.blend';out=base/'scene_candidate_r47.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
for unit in [101,102]:
 o=next(o for o in bpy.data.objects if o.get('program_key')==f'{unit}_living_sectional');m=o.data;adj=[[] for _ in m.vertices]
 for edge in m.edges:a,b=edge.vertices;adj[a].append(b);adj[b].append(a)
 pending=set(range(len(m.vertices)));components=[]
 while pending:
  stack=[pending.pop()];ids=[]
  while stack:
   i=stack.pop();ids.append(i)
   for j in adj[i]:
    if j in pending:pending.remove(j);stack.append(j)
  pts=[m.vertices[i].co for i in ids];bounds=[[min(p[k] for p in pts) for k in range(3)],[max(p[k] for p in pts) for k in range(3)]];components.append((set(ids),bounds))
 expected=[[.01,.6,.36],[.27,1.6,.88]];targets=[(ids,b) for ids,b in components if max(abs(b[j][k]-expected[j][k]) for j in range(2) for k in range(3))<1e-5];assert len(targets)==1;target=targets[0][0];main=next(ids for ids,b in components if abs(b[0][0]-.01)<1e-5 and b[0][1]<-1.59 and abs(b[1][0]-.27)<1e-5 and b[1][2]>.879)
 def front_polys(ids):
  result=[]
  for f in m.polygons:
   if f.vertices[0] not in ids or f.normal.x<.999 or abs(f.center.x-.27)>1e-5:continue
   poly=Polygon([(m.vertices[i].co.y,m.vertices[i].co.z) for i in f.vertices])
   if poly.is_valid and poly.area>1e-9:result.append(poly)
  return unary_union(result)
 area=front_polys(target).intersection(front_polys(main)).area;assert area>.1
 oldbounds=[[min(v.co[k] for v in m.vertices) for k in range(3)],[max(v.co[k] for v in m.vertices) for k in range(3)]];oldcount=len(m.polygons);bm=bmesh.new();bm.from_mesh(m);bm.verts.ensure_lookup_table();bmesh.ops.delete(bm,geom=[bm.verts[i] for i in target],context='VERTS');bm.to_mesh(m);bm.free();m.update();newbounds=[[min(v.co[k] for v in m.vertices) for k in range(3)],[max(v.co[k] for v in m.vertices) for k in range(3)]];assert max(abs(oldbounds[j][k]-newbounds[j][k]) for j in range(2) for k in range(3))<1e-6
 rows.append({'object':o.name,'removed_faces':oldcount-len(m.polygons),'removed_vertices':len(target),'removed_local_bounds':expected,'exact_coplanar_front_overlap_area_m2':area,'outer_bounds_unchanged':True})
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r47.json').write_text(json.dumps({'source':str(src),'candidate':str(out),'source_sha256':sha,'trigger':'Black-region first rays hit white sofa back. SectionalSofaFactory creates a short back fully contained in the long back,with coincident front caps.','change':'Only redundant back connected component removed on each mirrored sofa;body outer bounds,materials,light,exposure and native pillow shading unchanged.','sofas':rows,'photorealism_accepted':False,'requires':'same-camera46/47render to test black-area causality;shape/cloth/lighting and full-scene regression still required'},indent=2));print('SAVED',out,flush=True)
