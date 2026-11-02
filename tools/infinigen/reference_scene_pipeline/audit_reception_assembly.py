"""Bounded native reception panel joint/monitor support audit;raw saved mesh,not full-scene QA."""
import hashlib,json,argparse
from pathlib import Path
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

def audit_object(obj):
 me=obj.data;graph={v.index:set() for v in me.vertices};components=[]
 for e in me.edges:
  a,b=e.vertices;graph[a].add(b);graph[b].add(a)
 while graph:
  todo=[next(iter(graph))];ids=set()
  while todo:
   i=todo.pop()
   if i in ids:continue
   ids.add(i);todo.extend(graph.get(i,set())-ids)
  for i in ids:graph.pop(i,None)
  vs=[me.vertices[i].co for i in ids];components.append((ids,[min(v[k] for v in vs) for k in range(3)],[max(v[k] for v in vs) for k in range(3)]))
 def size(c,dims):return all(abs(c[2][k]-c[1][k]-d)<1e-5 for k,d in enumerate(dims))
 bases=[c for c in components if size(c,(.2,.22,.012))];fronts=[c for c in components if abs(c[2][0]-c[1][0]-.04)<1e-5 and abs(c[2][2]-1.1)<1e-5];sides=[c for c in components if abs(c[2][1]-c[1][1]-.04)<1e-5 and abs(c[2][2]-.74)<1e-5]
 if len(bases)!=1 or len(fronts)!=1 or len(sides)!=2:return {'object':obj.name,'pass':False,'reason':'native family components ambiguous','counts':[len(bases),len(fronts),len(sides)]}
 ids,lo,hi=bases[0];x,y=(lo[0]+hi[0])/2,(lo[1]+hi[1])/2
 faces=[tuple(p.vertices) for p in me.polygons if not any(i in ids for i in p.vertices) and max(me.vertices[i].co.z for i in p.vertices)<=.78001]
 tree=BVHTree.FromPolygons([v.co.copy() for v in me.vertices],faces);hit,n,i,dist=tree.ray_cast(Vector((x,y,lo[2]+.002)),Vector((0,0,-1)),.2);gap=lo[2]-hit.z if hit else None;joints=[fronts[0][1][0]-c[2][0] for c in sides]
 return {'object':obj.name,'monitor_support_gap_m':gap,'side_front_gap_m':joints,'pass':gap is not None and -.0001<=gap<=.001 and all(.0005<=g<=.003 for g in joints)}

def main():
 p=argparse.ArgumentParser();p.add_argument('--blend',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 with bpy.data.libraries.load(str(a.blend.resolve()),link=False) as (src,dst):dst.objects=[n for n in src.objects if 'ReceptionDeskFactory' in n]
 objects=[o for o in dst.objects if o and o.type=='MESH'];rows=[audit_object(o) for o in objects];errors=[v for v in rows if not v['pass']]
 if not rows:errors.append({'reason':'native reception missing'})
 out={'source':str(a.blend.resolve()),'source_sha256':hashlib.sha256(a.blend.read_bytes()).hexdigest(),'auditor_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'records':rows,'errors':errors,'photorealism_accepted':False,'scope':'Native raw reception panel clearances andactual work-surface ray below monitor base;not evaluated modifiers,continuous room collision,opening/navigation orvisual acceptance.'};a.out.write_text(json.dumps(out,indent=2));print(json.dumps({'records':rows,'errors':len(errors)}));return bool(errors)
if __name__=='__main__':raise SystemExit(main())
