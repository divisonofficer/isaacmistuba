import bpy,json,hashlib
from pathlib import Path
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';a=json.loads((d/'bedroom110_build.json').read_text());audit=json.loads((d/'bedroom110_lamp_support_audit.json').read_text());src=Path(a['candidate']);dst=src.with_name('scene_candidate_r111_draft.blend');assert not dst.exists();bpy.ops.wm.open_mainfile(filepath=str(src));moves=[]
for row,check in zip(a['replacements'],audit['rows']):
 assert abs(check['max_gap_m']-check['min_gap_m'])<1e-6;dz=-check['max_gap_m']+.0001
 for name in row['lamp_objects_moved']:bpy.data.objects[name].location.z+=dz
 moves.append({'objects':row['lamp_objects_moved'],'dz_m':dz,'expected_contact_gap_m':.0001})
bpy.ops.wm.save_as_mainfile(filepath=str(dst));(d/'bedroom111_support_fix.json').write_text(json.dumps({'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'candidate':str(dst),'candidate_sha256':hashlib.sha256(dst.read_bytes()).hexdigest(),'moves':moves,'scope':'Lamp vertical contact correction only. Actual reopened audit still required.','accepted':False},indent=2));print('BEDROOM111_CONTACT_FIX_SAVED')
