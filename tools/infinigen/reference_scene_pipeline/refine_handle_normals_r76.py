"""Controlled handle-only sharp-edge/smooth test; no geometry or materials changed."""
import bpy,json,hashlib
from pathlib import Path
root=Path('/jarvis/project/robomituba');base=root/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';src=base/'scene_candidate_r74.blend';out=base/'scene_candidate_r76.blend';assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
for o in bpy.data.objects:
 if o.type!='MESH' or 'DoorFactory' not in o.name:continue
 m=o.data;a=m.attributes.get('handle');assert a and a.domain=='POINT';ids={i for i,v in enumerate(a.data) if v.value>.5};before=[(p.material_index,tuple(p.vertices),p.use_smooth) for p in m.polygons];edges=0;faces=0
 for e in m.edges:
  if all(i in ids for i in e.vertices):edges+=int(e.use_edge_sharp);e.use_edge_sharp=False
 for p in m.polygons:
  if all(i in ids for i in p.vertices):p.use_smooth=True;faces+=1
  else:assert before[p.index]==(p.material_index,tuple(p.vertices),p.use_smooth)
 rows.append({'door':o.name,'handle_faces_smoothed':faces,'sharp_handle_edges_cleared':edges})
assert len(rows)==12;bpy.ops.wm.save_as_mainfile(filepath=str(out));(root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/realism_refinement_r76.json').write_text(json.dumps({'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'candidate':str(out),'changes':rows,'hypothesis':'native sharp edge flags preserve faceted reflections despite r75 subdivision;test handle-only normal smoothing from r74','photorealism_accepted':False},indent=2))
