"""Saved-source rays through six physical panes, perimeter coverage and frame fit."""
import bpy,json,hashlib,math
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';S=R/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r91.blend';O=D/'east_glazing_saved_audit_r91.json';assert not O.exists();meta=json.loads((D/'realism_refinement_r91.json').read_text());bpy.ops.wm.open_mainfile(filepath=str(S));dg=bpy.context.evaluated_depsgraph_get();normal=Vector((1,.08,0)).normalized();tangent=Vector((-.08,1,0)).normalized();trees={};errors=[]
for o in bpy.context.scene.objects:
 if o.type!='MESH' or o.hide_render or not o.name.endswith(('.wall','.exterior')):continue
 e=o.evaluated_get(dg);m=e.to_mesh();trees[o.name]=BVHTree.FromPolygons([o.matrix_world@v.co for v in m.vertices],[list(f.vertices) for f in m.polygons]);e.to_mesh_clear()
def hits(point):
 origin=Vector(point)-normal*.6;result=[]
 for name,t in trees.items():
  p,n,i,d=t.ray_cast(origin,normal,1.2)
  if p is not None:result.append({'object':name,'point':list(p),'distance_m':d})
 return result
panes=[];frames=[]
for row in meta['records']:
 o=bpy.data.objects[row['object']];e=o.evaluated_get(dg);m=e.to_mesh();coords=[o.matrix_world@v.co for v in m.vertices];ns=[p.dot(normal) for p in coords];frames.append({'object':o.name,'normal_min':min(ns),'normal_max':max(ns),'normal_depth_m':max(ns)-min(ns),'covers_both_wall_planes':min(ns)<=15.8401 and max(ns)>=15.949})
 if not frames[-1]['covers_both_wall_planes']:errors.append('Frame does not cover wall thickness:'+o.name)
 ids={i for i,mat in enumerate(m.materials) if mat and mat.name.startswith('R91_physical_clear_glass')};vs={i for f in m.polygons if f.material_index in ids for i in f.vertices};adj={i:set() for i in vs};edges={}
 for f in m.polygons:
  if f.material_index not in ids:continue
  v=list(f.vertices)
  for k,a in enumerate(v):
   b=v[(k+1)%len(v)];adj[a].add(b);adj[b].add(a);key=tuple(sorted((a,b)));edges[key]=edges.get(key,0)+1
 left=set(vs)
 while left:
  stack=[left.pop()];component=set(stack)
  while stack:
   for q in adj[stack.pop()]:
    if q in left:left.remove(q);component.add(q);stack.append(q)
  pts=[coords[i] for i in component];center=sum(pts,Vector())/len(pts);zlo=min(p.z for p in pts);zhi=max(p.z for p in pts);thick=max(p.dot(normal) for p in pts)-min(p.dot(normal) for p in pts);bad=sum(n!=2 for (a,b),n in edges.items() if a in component and b in component);rays=[]
  for z in [zlo+.15,(zlo+zhi)/2,zhi-.15]:
   p=center.copy();p.z=z;found=hits(p);rays.append({'point':list(p),'blocking_shell_hits':found})
   if found:errors.append('Blocked pane '+o.name+' z'+str(z))
  if bad or not .007<thick<.009:errors.append('Invalid pane thickness/closure '+o.name)
  panes.append({'object':o.name,'vertices':len(component),'thickness_m':thick,'nonmanifold_edge_count':bad,'rays':rays})
 e.to_mesh_clear()
piers=[]
for y in [10.4,13.5,17.8]:
 point=normal*((15.8401+15.949)/2)+tangent*((y-normal.y*((15.8401+15.949)/2))/tangent.y);point.z=1.4;found=hits(point);piers.append({'y':y,'hits':found})
 if not found:errors.append('Expected retained pier missing at y'+str(y))
if len(panes)!=6:errors.append('Expected6 panes got'+str(len(panes)))
h=hashlib.sha256(S.read_bytes()).hexdigest();assert h==meta['candidate_sha256'];report={'source':str(S),'source_sha256':h,'panes':panes,'frames':frames,'retained_pier_rays':piers,'errors':errors,'pass':not errors,'scope':'Six closed8mm panes,18 evaluated structural-shell clearance rays,3 retained-pier rays,frame depth envelope. Not full wall collision/volume/nav or appearance acceptance.','photorealism_accepted':False};O.write_text(json.dumps(report,indent=2)+'\n');print('SAVED_GLAZING_AUDIT',len(panes),len(errors),flush=True);assert not errors,errors
