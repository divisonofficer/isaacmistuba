"""Scene-local extraction: select floor boundary by area, not vertex count.

Door threshold slivers have more vertices than small rectangular rooms. The
shared extractor's longest-loop rule selected those slivers for the powder room
and corridors. Keep the shared source untouched and fix only this invocation.
"""
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from room_planner import extract_rooms as shared

def outline(floor):
 me=floor.data
 counts={}
 for poly in me.polygons:
  for edge in poly.edge_keys:counts[edge]=counts.get(edge,0)+1
 nbr={}
 for (a,b),n in counts.items():
  if n==1:nbr.setdefault(a,[]).append(b);nbr.setdefault(b,[]).append(a)
 seen=set();loops=[]
 for start in nbr:
  if start in seen:continue
  loop=[];prev=None;cur=start
  while cur not in seen:
   loop.append(cur);seen.add(cur)
   nxt=[v for v in nbr[cur] if v!=prev]
   if not nxt or nxt[0]==start:break
   prev,cur=cur,nxt[0]
  pts=[floor.matrix_world@me.vertices[i].co for i in loop]
  if len(pts)>=3:loops.append([(p.x,p.y) for p in pts])
 def area(pts):
  return abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(pts,pts[1:]+pts[:1])))
 pts=max(loops,key=area);out=[]
 for i,p in enumerate(pts):
  a,c=pts[i-1],pts[(i+1)%len(pts)]
  if abs((p[0]-a[0])*(c[1]-p[1])-(p[1]-a[1])*(c[0]-p[0]))>1e-4:out.append(p)
 return out

shared.outline=outline
if __name__=='__main__':raise SystemExit(shared.main())
