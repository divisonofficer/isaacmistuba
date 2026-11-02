"""Restore low-stretch sewn-panel dimensions from native pre-solidify UVs,retain pressure loft/folds."""
import bpy,bmesh,json,numpy as np,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[3];ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=ref/'native_pillow_prototypes.blend';out=ref/'native_pillow_panel_rest_prototypes.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
for o in bpy.data.objects:
 if o.type!='MESH':continue
 m=o.data;uv=m.uv_layers.active;values=[[] for _ in m.vertices]
 for f in m.polygons:
  for li in f.loop_indices:values[m.loops[li].vertex_index].append(list(uv.data[li].uv))
 spread=max(np.ptp(v,axis=0).max() for v in values);assert spread<1e-5
 means=np.asarray([np.mean(v,axis=0) for v in values]);coords=np.asarray([list(v.co) for v in m.vertices]);corr=np.corrcoef(np.concatenate([coords[:,:2],means],axis=1).T);axes=[int(np.argmax(np.abs(corr[k,2:]))) for k in [0,1]];assert len(set(axes))==2 and all(abs(corr[k,2+axes[k]])>.98 for k in [0,1]);dims=[float(o['factory_width_m']),float(o['factory_size_m'])]
 maximum=0
 for k in [0,1]:
  axis=axes[k];lo,hi=means[:,axis].min(),means[:,axis].max();target=(means[:,axis]-(lo+hi)/2)/(hi-lo)*dims[k]*np.sign(corr[k,2+axis]);updated=.2*coords[:,k]+.8*target;maximum=max(maximum,float(np.max(np.abs(updated-coords[:,k]))));coords[:,k]=updated
 for v,co in zip(m.vertices,coords):v.co=co
 m.update();bpy.context.view_layer.update();ev=o.evaluated_get(bpy.context.evaluated_depsgraph_get());em=ev.to_mesh();lo=[min(v.co[k] for v in em.vertices) for k in range(3)];hi=[max(v.co[k] for v in em.vertices) for k in range(3)];tree=BVHTree.FromPolygons([v.co for v in em.vertices],[list(f.vertices) for f in em.polygons]);recessions=[]
 for axis in [0,1]:
  for sign in [-1,1]:
   origin=Vector((0,0,0));origin[axis]=sign;hit,_,_,_=tree.ray_cast(origin,-origin,2);assert hit is not None;recessions.append((hi[axis] if sign>0 else -lo[axis])-sign*hit[axis])
 ev.to_mesh_clear();o.name=o.name.replace('NativePressurePillow','NativePanelRestPillow');rows.append({'object':o.name,'uv_maximum_shared_vertex_spread':float(spread),'uv_axes_for_xy':axes,'correlations':[float(corr[k,2+axes[k]]) for k in [0,1]],'panel_rest_blend':.8,'maximum_inplane_correction_m':maximum,'edge_midpoint_recession_m':recessions,'gross_outline_gate_pass':max(recessions)<.015,'loft_preserved':True})
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'native_pillow_panel_rest_prototypes.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'method':'Post-solve low-stretch panel constraint from verified unsplit native UV;preserves native pressure Z loft and folds. Not claimed as a new full physics solve.','prototypes':rows,'photorealism_accepted':False,'requires':'outline gate,actual placement/contact,self-overlap check and direct/independent image review'},indent=2));print(json.dumps(rows,indent=2),flush=True)
