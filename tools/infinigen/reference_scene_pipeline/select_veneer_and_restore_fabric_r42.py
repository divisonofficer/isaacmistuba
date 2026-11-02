"""Keep verified veneer projection fix; undo visually weaker experimental surface fabric mapping."""
import bpy,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r41.blend';out=base/'scene_candidate_r42.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));m=bpy.data.materials['BreakoutR30_fine_blue_upholstery'];rows=[]
for o in bpy.data.objects:
 if o.type=='MESH' and o.get('program_key','').startswith('breakout_chair') and '_upholstery' in o.get('program_key',''):
  o.data.materials.clear();o.data.materials.append(m);rows.append(o.name)
assert len(rows)==8;bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r42.json').write_text(json.dumps({'source':str(src),'candidate':str(out),'source_sha256':sha,'decision':'Retain41 cabinetry FLAT projection;restore38 fabric response on8shaped pads.39UV sampling weakened back fabric and stretched sides;not adopted.40shallow compression/thread geometry retained provisionally as manufactured detail,not a photorealism pass.','restored_objects':rows,'lighting_geometry_from41':'unchanged','photorealism_accepted':False,'requires':'same-camera regression and highseverity chair defect remains unresolved'},indent=2));print('SAVED',out,flush=True)
