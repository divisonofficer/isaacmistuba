"""Expose actual shirt proportions instead of viewing all garments almost edge-on."""
import bpy,json,hashlib,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r33.blend';out=base/'scene_candidate_r34.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
for o in bpy.data.objects:
 key=o.get('program_key','')
 if '_native_garment_' not in key:continue
 unit,_,_,tier,g=key.split('_');tier=int(tier);g=int(g);old=o.rotation_euler.z;o.rotation_euler.z=.90+(g%3-1)*.035;o.location.y+=.035;angle=o.rotation_euler.z;railz=1.8 if tier==0 else 1.05
 hanger=next(x for x in bpy.data.objects if x.get('program_key')==f'{unit}_hanger_{tier}_{g}');pts=[(.28+math.cos(angle)*x,o.location.y+math.sin(angle)*x,z) for x,z in [(-.18,railz-.13),(0,railz-.055),(.18,railz-.13),(-.18,railz-.13)]]
 for p,co in zip(hanger.data.splines[0].points,pts):p.co=(*co,1)
 hook=next(x for x in bpy.data.objects if x.get('program_key')==f'{unit}_hook_{tier}_{g}');hook.location.y+=.035;rows.append({'object':o.name,'old_yaw':old,'new_yaw':angle,'rail_center_shift_m':.035})
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r34.json').write_text(json.dumps({'source':str(src),'candidate':str(out),'reason':'r33 closeup still reads long flat: largely edge-on shirts compress apparent body width; neckline is cropped by old camera.','changes':rows,'requires':['physical frame containment','fresh same-camera wider neckline framing, not a different-camera success claim','cloth/cloth intersection assessment'],'photorealism_accepted':False},indent=2));print('SAVED',out)
