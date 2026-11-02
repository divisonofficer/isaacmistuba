import bpy,json,numpy as np
from pathlib import Path
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';bpy.ops.wm.open_mainfile(filepath=str(r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r93.blend'));o=bpy.data.objects['PanelDoorFactory(4643175).spawn_asset(6)'];m=o.data;parent=list(range(len(m.vertices)))
def root(i):
 while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
 return i
for e in m.edges:
 a,b=e.vertices;parent[root(a)]=root(b)
groups={}
for f in m.polygons:groups.setdefault(root(f.vertices[0]),[]).append(f)
rows=[]
for faces in groups.values():
 ids={v for f in faces for v in f.vertices};pts=np.array([tuple(o.matrix_world@m.vertices[i].co) for i in ids]);values,axes=np.linalg.eigh(np.cov(pts[:,:2].T));horizontal=axes[:,1];normal=axes[:,0];pr=np.column_stack([pts[:,:2]@horizontal,pts[:,:2]@normal,pts[:,2]]);lo=pr.min(axis=0);hi=pr.max(axis=0);rows.append({'faces':len(faces),'slots':sorted(set(f.material_index for f in faces)),'polygon_area':sum(f.area for f in faces),'width_axis':horizontal.tolist(),'normal_axis':normal.tolist(),'projected_lo':lo.tolist(),'projected_hi':hi.tolist(),'dimensions':(hi-lo).tolist(),'world_lo':pts.min(axis=0).tolist(),'world_hi':pts.max(axis=0).tolist(),'face_indices':[f.index for f in faces]})
rows.sort(key=lambda x:-x['polygon_area']);(d/'native_door_components_r93.json').write_text(json.dumps({'object':o.name,'components':rows,'scope':'Connected geometry parts,not yet semantic leaf/frame identification.'},indent=2));print('DOOR_COMPONENT_PROBE_COMPLETE',len(rows))
