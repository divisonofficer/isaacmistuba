"""Reviewed static lower-band compression of native pressure contour;not a physics solve."""
import numpy as np
from pressure_contour_refinement import make_shape as pressure_shape
from pillow_shape_refinement import self_overlap

def make_shape(native,width,height,depth,angle,roll):
 mesh,_=pressure_shape(native,width,height,depth,angle,roll)
 a=np.asarray([list(v.co) for v in mesh.vertices]);before=a.copy();low=a[:,2].min();L=.120;alpha=.15;mask=a[:,2]<low+L;t=(a[mask,2]-low)/L
 a[mask,2]=low+L*(alpha*t+(1-alpha)*t**7*(28-48*t+21*t*t))
 mesh.vertices.foreach_set('co',a.astype(np.float32).ravel());mesh.update();assert not self_overlap(mesh),'compressed contour self-overlap'
 return mesh,float((before[:,2]-a[:,2]).max())
