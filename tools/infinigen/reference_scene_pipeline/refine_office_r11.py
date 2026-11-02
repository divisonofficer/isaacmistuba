"""Second material trial after direct A/B found weak carpet detail in r10."""
import json
from pathlib import Path
import bpy
from material_detail import carpet
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r10.blend'))
cp=next(im for im in bpy.data.images if im.name.startswith('cp_'));new=carpet(cp,ref/'pbr_assets')
count=0
for o in bpy.data.objects:
    if o.name.endswith('.floor') and o.name.startswith(('office','utility')):
        o.data.materials.clear();o.data.materials.append(new);count+=1
out=base/'scene_candidate_r11.blend';bpy.ops.wm.save_as_mainfile(filepath=str(out))
(ref/'material_detail_r11.json').write_text(json.dumps({'source':'scene_candidate_r10.blend','carpet_floor_objects':count,'normal_source':'fabric_0022/normal_gl.png, Non-Color, world normal basis for horizontal floor','roughness_source':'fabric_0022/roughness.jpg, Non-Color','scan_repeat_metres':.25,'visual_acceptance':False},indent=2))
