"""Repair an actual frame-bound regression after garment yaw change, without altering the gate."""
import bpy,json,hashlib,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r34.blend';out=base/'scene_candidate_r35.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));changes=[]
for o in bpy.data.objects:
 key=o.get('program_key','')
 if '_native_garment_' not in key:continue
 points=[o.matrix_local@v.co for v in o.data.vertices];lo=min(p.y for p in points);hi=max(p.y for p in points);delta=max(0,-1.19-lo) if lo< -1.20 else min(0,.29-hi) if hi>.30 else 0
 if not delta:continue
 unit,_,_,tier,g=key.split('_');o.location.y+=delta
 for suffix in ['hanger','hook']:
  item=next(x for x in bpy.data.objects if x.get('program_key')==f'{unit}_{suffix}_{tier}_{g}');item.location.y+=delta
 changes.append({'object':o.name,'previous_local_y':[lo,hi],'local_y_shift_m':delta,'hanger_and_hook_shifted':True})
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r35.json').write_text(json.dumps({'source':str(src),'candidate':str(out),'reason':'r34 actual containment gate caught one garment6.87mm beyond allowed frame bounds. Gate kept unchanged.','changes':changes,'photorealism_accepted':False},indent=2));print('SAVED',out,changes)
