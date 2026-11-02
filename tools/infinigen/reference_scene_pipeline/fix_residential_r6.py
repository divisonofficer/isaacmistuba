"""Clear dining-chair obstruction of bedroom3 approach, measured by route audit."""
import bpy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r5.blend'))
for o in bpy.data.objects:
 key=o.get('program_key','')
 if key.startswith(('101_dining_','102_dining_')):o.location.x+=.8 if key.startswith('101_') else -.8
bpy.data.objects['Residential03_r4_upper_stair_shaft_cap']['audit_ceiling_surface']=True
out=base/'scene_candidate_r6.blend';assert not out.exists();bpy.ops.wm.save_as_mainfile(filepath=str(out))
