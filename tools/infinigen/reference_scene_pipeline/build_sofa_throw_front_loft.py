"""Controlled original versus modest front-only convex loft on native mesh; no new physics."""
import bpy,json,hashlib
import numpy as np
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path('/jarvis/project/robomituba/data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03');source=r/'sofa_throw_face_studio02/original.blend';out=r/'sofa_throw_front_loft_studio03';assert not out.exists();out.mkdir();bpy.ops.wm.open_mainfile(filepath=str(source));o=bpy.data.objects['original'];native=o.data.copy();a=np.asarray([list(v.co) for v in native.vertices]);C=a.mean(0);eig,axes=np.linalg.eigh(np.cov((a-C).T));N,U,V=axes[:,0],axes[:,2],axes[:,1]
if N[0]<0:N=-N
ru=max(abs((a-C)@U));rv=max(abs((a-C)@V));rn=max(abs((a-C)@N));delta=[]
for kind in ['original','front_loft']:
 o.data=native.copy()
 if kind=='front_loft':
  for v in o.data.vertices:
   q=np.array(v.co)-C;u=np.dot(q,U)/ru;w=np.dot(q,V)/rv;t=max(0,min(1,np.dot(q,N)/(rn*.5)));mask=t*t*(3-2*t);amount=.025*max(0,1-u*u)*max(0,1-w*w)*mask;v.co=Vector(np.array(v.co)+N*amount);delta.append(amount)
  o.data.update();polys=[list(f.vertices) for f in o.data.polygons];points=[v.co.copy() for v in o.data.vertices];tree=BVHTree.FromPolygons(points,polys);sets=[set(f) for f in polys];coords=[{tuple(round(float(x),7) for x in points[k]) for k in f} for f in polys];overlap=[(i,j) for i,j in tree.overlap(tree) if j>i and not sets[i]&sets[j] and not coords[i]&coords[j]];assert not overlap,('front loft self-overlap candidates',len(overlap))
 o.location=(0,0,-min(v.co.z for v in o.data.vertices));bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out/(kind+'.blend')))
(out/'views.json').write_text((r/'sofa_throw_face_studio02/views.json').read_text());(out/'provenance.json').write_text(json.dumps({'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'change':'front-only convex offset up to25mm, smooth mask with zero offset on back/edge; native topology/material/UV retained; all snapshots use one object/fixed world light and camera','maximum_actual_offset_m':max(delta),'mean_offset_m':float(np.mean(delta)),'initial_depth_not_thin':'previous loft audit centre17.2cm; not treating bbox depth as underfilling','self_overlap_candidates':len(overlap),'limits':'static authored shape test, not cloth pressure/load solve or room integration','photorealism_accepted':False},indent=2));print(out,flush=True)
