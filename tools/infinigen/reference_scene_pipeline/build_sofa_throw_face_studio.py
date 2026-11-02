"""One visible object per snapshot, fixed camera/lights: inspect front/back shape, not bbox thickness."""
import bpy,json,math,hashlib
import numpy as np
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
r=Path('/jarvis/project/robomituba/data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03');source=r/'sofa_throw_depth_studio01/studio.blend';out=r/'sofa_throw_face_studio02';assert not out.exists();out.mkdir();bpy.ops.wm.open_mainfile(filepath=str(source));o=bpy.data.objects['original'];native=o.data.copy()
for other in list(bpy.data.objects):
 if other.name in ['smooth_only','filled_depth']:bpy.data.objects.remove(other,do_unlink=True)
o.parent=None;o.matrix_world=Matrix.Identity(4);a=np.asarray([list(v.co) for v in native.vertices]);C=a.mean(0);eig,axes=np.linalg.eigh(np.cov((a-C).T));N,U,V=axes[:,0],axes[:,2],axes[:,1]
if N@np.array([.85,-.65,.27])<0:N=-N
ru=max(abs((a-C)@U));rv=max(abs((a-C)@V));tree=BVHTree.FromPolygons([v.co for v in native.vertices],[list(f.vertices) for f in native.polygons]);samples=[]
for u,v in [(0,0),(.5,0),(-.5,0),(0,.5),(0,-.5),(.5,.5),(-.5,-.5)]:
 p=Vector(C+U*ru*u+V*rv*v);n=Vector(N);f=tree.ray_cast(p+n,-n,2)[0];b=tree.ray_cast(p-n,n,2)[0];assert f is not None and b is not None;samples.append({'uv':[u,v],'front_depth_m':float(np.dot(np.array(f)-C,N)),'back_depth_m':float(np.dot(np.array(b)-C,N))})
X=np.asarray([[*p['uv'],1] for p in samples]);metrics={}
for side in ['front','back']:
 z=np.asarray([p[side+'_depth_m'] for p in samples]);coef=np.linalg.lstsq(X,z,rcond=None)[0];metrics[side+'_sampled_curvature_rms_m']=float(np.sqrt(np.mean((z-X@coef)**2)))
R=2*np.outer(V,V)-np.eye(3);assert abs(np.linalg.det(R)-1)<1e-8
for kind in ['original','turned']:
 o.data=native.copy()
 if kind=='turned':
  for v in o.data.vertices:v.co=Vector(C+R@(np.array(v.co)-C))
 o.location=(0,0,-min(v.co.z for v in o.data.vertices));bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out/(kind+'.blend')))
view={'name':'sofa_throw_profile','location':[.85,-.65,.48],'target':[0,0,.21],'hfov':40,'render_width':768,'samples':32};(out/'views.json').write_text(json.dumps([view],indent=2));(out/'provenance.json').write_text(json.dumps({'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'comparison':'same camera and fixed lights; only one cushion visible in each snapshot; native body turned180deg about its vertical principal axis, then floor-aligned','samples':samples,'metrics':metrics,'limits':'static orientation diagnostic,not new physics or room integration; earlier three-object study is a shape preview with different world-light positions and not strict appearance A/B','photorealism_accepted':False},indent=2));print(metrics,flush=True)
