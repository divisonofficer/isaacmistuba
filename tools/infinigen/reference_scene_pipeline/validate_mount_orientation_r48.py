"""Pre-render actual mounting-plate orientation correction; candidate47 has no review images."""
import bpy,bmesh,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r47.blend';out=base/'scene_candidate_r48.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
for o in bpy.data.objects:
 if '_back_mount_' not in o.get('program_key',''):continue
 o.data=o.data.copy();bm=bmesh.new();bm.from_mesh(o.data);before=bm.calc_volume(signed=True);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));after=bm.calc_volume(signed=True);assert after>0;bm.to_mesh(o.data);bm.free();rows.append({'object':o.name,'volume_before_m3':before,'volume_after_m3':after,'orientation_recomputed':True,'signed_volume_changed':abs(after-before)>1e-12})
assert len(rows)==8;bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r48.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'inherits_geometry':'realism_refinement_r47.json','mount_orientation':rows,'note':'Pre-render plate winding validation;source47 unrendered. Actual comparison is46vs48.','photorealism_accepted':False},indent=2));print('SAVED',out,rows,flush=True)
