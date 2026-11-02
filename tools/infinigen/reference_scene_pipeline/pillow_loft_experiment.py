"""Native pillow geometry kernel;corner-local C1 blend plus legacy comparator for asset preflight."""
import bpy,math
import numpy as np
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree

def tree(mesh):return BVHTree.FromPolygons([v.co.copy() for v in mesh.vertices],[list(f.vertices) for f in mesh.polygons])

def self_overlap(mesh):
 t=tree(mesh);sets=[set(f.vertices) for f in mesh.polygons];coords=[{tuple(round(float(x),7) for x in mesh.vertices[i].co) for i in f.vertices} for f in mesh.polygons];return [(i,j) for i,j in t.overlap(t) if j>i and not sets[i]&sets[j] and not coords[i]&coords[j]]

def make_shape(native,width,height,depth,angle,roll,corner_mode="local_smooth",loft_mode="native"):
 a=np.array([list(v.co) for v in native.vertices]);C=(a.min(0)+a.max(0))/2;H=(a.max(0)-a.min(0))/2;R=Matrix.Rotation(angle,4,'Y')@Matrix.Rotation(roll,4,'X');mesh=native.copy()
 def deform(q):
  u=(q.x-C[0])/H[0];v=(q.y-C[1])/H[1];d=(q.z-C[2])/H[2];bell=max(0,1-u*u)*max(0,1-v*v)
  a,b=width*.5,height*.5;radius=.05 if width>.5 else .035;py,pz=a*u,b*v
  if corner_mode=="legacy_radial":
   s=max(abs(u),abs(v));py=pz=0
   if s>1e-10:
    px,pz0=a*u/s,b*v/s;length=math.hypot(px,pz0);dx,dy=abs(px)/length,abs(pz0)/length
    if dx>1e-10 and a*dy/dx<=b-radius:t=a/dx
    elif dy>1e-10 and b*dx/dy<=a-radius:t=b/dy
    else:
     dot=dx*(a-radius)+dy*(b-radius);t=dot+math.sqrt(max(0,dot*dot-((a-radius)**2+(b-radius)**2-radius**2)))
    py=math.copysign(dx*t*s,u);pz=math.copysign(dy*t*s,v)
  else:
   assert corner_mode=="local_smooth"
   # Identity outside the corner box;zero blend derivative along its inner edges.
   cx=max(0,abs(py)-(a-radius));cz=max(0,abs(pz)-(b-radius))
   if cx>0 and cz>0:
    sx=min(1,cx/radius);sz=min(1,cz/radius);w=(sx*sx*(3-2*sx))*(sz*sz*(3-2*sz))
    nx=cx*(1-w*(1-math.sqrt(max(.1,1-.5*sz*sz))));nz=cz*(1-w*(1-math.sqrt(max(.1,1-.5*sx*sx))))
    py=math.copysign(a-radius+nx,py);pz=math.copysign(b-radius+nz,pz)
  rim_half=.012 if width>.5 else .010
  newdepth=d*depth*(.38+.92*bell)+rim_half*math.tanh(d/.035)
  if loft_mode=="filled":
   # Preserve rim closure; use a continuous stuffing envelope across each face.
   sign=math.tanh(d/.035)
   newdepth=sign*(rim_half+depth*max(0,bell)**.65)+d*depth*.10*bell
  else:assert loft_mode=="native"
  return R@Vector((newdepth,py,pz))
 for v in mesh.vertices:v.co=deform(v.co)
 low=min(v.co.z for v in mesh.vertices);compression=0
 for v in mesh.vertices:
  dz=v.co.z-low
  if dz<.018:
   t=dz/.018;new=low+(.018*t*t if corner_mode=='legacy_radial' else .018*(-t*t*t+2*t*t));compression=max(compression,v.co.z-new);v.co.z=new
 mesh.polygons.foreach_set('use_smooth',np.ones(len(mesh.polygons),dtype=bool));mesh.update();assert not self_overlap(mesh), 'deformed native pillow self-overlap';return mesh,compression
