"""Clear the last true floor-polygon violations; retain all cameras."""
import json
from pathlib import Path
import bpy
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r7.blend'))
plant=bpy.data.objects['Office02_native_plant_2'];delta=Vector((14.0-plant.location.x,16.5-plant.location.y,0))
for o in bpy.data.objects:
    if o.get('program_key') in ['plant_2','pot_2','soil_2']:o.location+=delta
    if o.get('program_key') in ['support_west_storage','west_paper_stack']:o.location.y-=.12
out=base/'scene_candidate_r8.blend';bpy.ops.wm.save_as_mainfile(filepath=str(out))
(base/'correction_r8.json').write_text(json.dumps({'plant_delta':list(delta),'west_cabinet_delta_y':-.12,'reason':'true projected floor containment, not enclosing floor AABB','visual_acceptance':False},indent=2))
