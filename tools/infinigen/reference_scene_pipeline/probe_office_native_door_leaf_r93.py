import bpy,json,hashlib,numpy as np
from pathlib import Path
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';s=r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r93.blend';bpy.ops.wm.open_mainfile(filepath=str(s));rows=[]
for o in bpy.context.scene.objects:
 if o.type!='MESH' or 'DoorFactory(' not in o.name:continue
 slots=[]
 for i,mat in enumerate(o.data.materials):
  faces=[f for f in o.data.polygons if f.material_index==i];ids={v for f in faces for v in f.vertices};pts=np.array([tuple(o.matrix_world@o.data.vertices[v].co) for v in ids]);record={'slot':i,'material':mat.name if mat else None,'faces':len(faces)}
  if len(pts):
   ctr=pts.mean(axis=0);values,vecs=np.linalg.eigh(np.cov(pts[:,:2].T));width_axis=vecs[:,1];normal_axis=vecs[:,0];projected=np.column_stack([pts[:,:2]@width_axis,pts[:,:2]@normal_axis,pts[:,2]]);lo=projected.min(axis=0);hi=projected.max(axis=0);record.update(world_lo=pts.min(axis=0).tolist(),world_hi=pts.max(axis=0).tolist(),horizontal_width_axis=width_axis.tolist(),horizontal_normal_axis=normal_axis.tolist(),projected_lo=lo.tolist(),projected_hi=hi.tolist(),projected_dimensions=(hi-lo).tolist(),horizontal_eigenvalues=values.tolist())
  slots.append(record)
 rows.append({'object':o.name,'matrix_world':[list(v) for v in o.matrix_world],'slots':slots})
(d/'native_door_leaf_probe_r93.json').write_text(json.dumps({'source':str(s),'source_sha256':hashlib.sha256(s.read_bytes()).hexdigest(),'objects':rows,'scope':'Per-material-slot world/PCA envelopes only;positive identification of slots/leaf handedness requires source andvisual checks;no replacement.'},indent=2));print('NATIVE_DOOR_LEAF_PROBE_COMPLETE',len(rows),flush=True)
