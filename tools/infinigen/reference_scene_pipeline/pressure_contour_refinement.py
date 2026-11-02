"""Exact axis/scale mapping used by independently reviewed moderate-contour studio."""
import numpy as np
from mathutils import Vector,Matrix
def make_shape(native,width,height,depth,angle,roll,**kw):
 a=np.asarray([list(v.co) for v in native.vertices]);c=(a.max(0)+a.min(0))/2;h=(a.max(0)-a.min(0))/2;m=native.copy();R=Matrix.Rotation(angle,4,"Y")@Matrix.Rotation(roll,4,"X")
 for v in m.vertices:
  q=(np.asarray(v.co)-c)/h;v.co=R@Vector((q[2]*depth,q[0]*width/2,q[1]*height/2))
 m.polygons.foreach_set('use_smooth',np.ones(len(m.polygons),dtype=bool));m.update();return m,0
