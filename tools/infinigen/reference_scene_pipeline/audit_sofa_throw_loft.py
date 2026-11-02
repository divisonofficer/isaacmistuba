"""Distinguish PCA extent from actual front/back loft and closed volume; no scene mutation."""
import bpy,bmesh,json
import numpy as np
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path('/jarvis/project/robomituba/data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/sofa_throw_depth_studio01');bpy.ops.wm.open_mainfile(filepath=str(r/'studio.blend'));rows=[]
for name in ['original','smooth_only','filled_depth']:
 o=bpy.data.objects[name];me=o.data;a=np.asarray([list(v.co) for v in me.vertices]);C=a.mean(0);eig,axes=np.linalg.eigh(np.cov((a-C).T));N,U,V=[axes[:,i] for i in [0,2,1]];ru=max(abs((a-C)@U));rv=max(abs((a-C)@V));tree=BVHTree.FromPolygons([v.co for v in me.vertices],[list(f.vertices) for f in me.polygons]);samples=[]
 for u,v in [(0,0),(.5,0),(-.5,0),(0,.5),(0,-.5),(.5,.5),(-.5,-.5)]:
  p=Vector(C+U*ru*u+V*rv*v);n=Vector(N);front=tree.ray_cast(p+n,-n,2)[0];back=tree.ray_cast(p-n,n,2)[0];samples.append({'uv':[u,v],'surface_separation_m':abs((front-back).dot(n)) if front is not None and back is not None else None})
 bm=bmesh.new();bm.from_mesh(me);volume=abs(bm.calc_volume(signed=True));nonmanifold=sum(not e.is_manifold for e in bm.edges);bm.free();rows.append({'object':name,'pca_normal_extent_m':float(np.ptp((a-C)@N)),'closed_signed_volume_m3':volume,'nonmanifold_edges':nonmanifold,'sampled_loft':samples})
(r/'loft_audit.json').write_text(json.dumps({'scope':'geometry-only raw meshes; sampled surface separation and volume, not load simulation or visual acceptance','variants':rows},indent=2));print(json.dumps(rows),flush=True)
