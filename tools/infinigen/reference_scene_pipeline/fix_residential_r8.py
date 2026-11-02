"""Use a three-seat dining layout; remove bedroom-door-side fourth chair."""
from pathlib import Path
import bpy
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r5.blend'))
# Moving entire dining sets narrowed the kitchen hall: rejected r6/r7.
# Three remaining seats preserve capacity without placing seating in door approach.
for o in list(bpy.data.objects):
 if o.get('program_key') in ('101_dining_chair_-1_-0.48','102_dining_chair_-1_-0.48'):bpy.data.objects.remove(o,do_unlink=True)
bpy.data.objects['Residential03_r4_upper_stair_shaft_cap']['audit_ceiling_surface']=True
out=base/'scene_candidate_r8.blend';assert not out.exists();bpy.ops.wm.save_as_mainfile(filepath=str(out))
