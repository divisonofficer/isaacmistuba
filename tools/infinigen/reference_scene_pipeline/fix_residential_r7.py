"""Declare the actual raised shaft cap for geometry ceiling measurements."""
from pathlib import Path
import bpy
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r6.blend'))
bpy.data.objects['Residential03_r4_upper_stair_shaft_cap']['audit_ceiling_surface']=True
out=base/'scene_candidate_r7.blend';assert not out.exists();bpy.ops.wm.save_as_mainfile(filepath=str(out))
