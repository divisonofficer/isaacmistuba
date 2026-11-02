"""Actual smooth-face compatibility correction only; no new geometry,light or shader change."""
import bpy,sys,json,hashlib,numpy as np
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'modules/infinigen'))
from infinigen.assets.utils.decorate import set_shade_smooth
base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r45.blend';out=base/'scene_candidate_r46.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
def coords_hash(mesh):
 data=np.empty(len(mesh.vertices)*3,dtype=np.float32);mesh.vertices.foreach_get('co',data);return hashlib.sha256(data.tobytes()).hexdigest()
for o in bpy.data.objects:
 if o.type!='MESH' or '_native_sofa_pillow_' not in o.get('program_key',''):continue
 before=coords_hash(o.data);smooth_before=sum(f.use_smooth for f in o.data.polygons);set_shade_smooth(o);assert coords_hash(o.data)==before and all(f.use_smooth for f in o.data.polygons);rows.append({'object':o.name,'smooth_faces_before':smooth_before,'smooth_faces_after':len(o.data.polygons),'unchanged_coordinates_sha256':before})
assert len(rows)==4;bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r46.json').write_text(json.dumps({'source':str(src),'candidate':str(out),'source_sha256':sha,'bpy_version':bpy.app.version_string,'trigger':'Native set_shade_smooth wrote legacyINTuse_smooth attribute but actual polygon flags werefalse on all4native pillows. Cube reproduced0/6smooth before fix and6/6after.','scope':'Actual smooth shading flags on4native pillow meshes only;coordinates,materials,lights,exposure unchanged. Legacy attribute preserved.','pillows':rows,'photorealism_accepted':False,'requires':'same-camera45/46full-pillow comparison;larger form/contact and lighting remain separate problems'},indent=2));print('SAVED',out,flush=True)
