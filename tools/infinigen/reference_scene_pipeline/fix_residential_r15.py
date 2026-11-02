"""Remove two doorway-side balcony pots after measured route regression."""
import bpy,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r14.blend'))
removed=[]
for o in list(bpy.data.objects):
 if o.get('reference_scene_owner')=='dual_unit_residential_floor_03' and o.get('program_key') in [f'{kind}_{i}' for i in (2,5) for kind in ('plant','pot','soil')]:removed.append(o.name);bpy.data.objects.remove(o,do_unlink=True)
out=base/'scene_candidate_r15.blend';assert not out.exists();bpy.ops.wm.save_as_mainfile(filepath=str(out))
(ref/'correction_r15.json').write_text(json.dumps({'source':'scene_candidate_r14.blend','removed':removed,'reason':'Doorway-side balcony pots reduced reachable standing area below 50%; preserve one supported plant per balcony and one per living room.','visual_acceptance':False},indent=2))
