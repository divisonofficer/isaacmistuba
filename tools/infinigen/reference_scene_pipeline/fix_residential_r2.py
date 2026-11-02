"""Correct actual measured furniture extents caught before full review batch."""
from pathlib import Path
import sys
import json
import bpy
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_home as ph
base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full'
assert not (base/'scene_candidate_r2.blend').exists(), 'Preserve the recorded r2 candidate; use a new revision for further corrections.'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r1.blend'))
floor=bpy.data.objects['bedroom_0/0.floor'];fz=max((floor.matrix_world@Vector(c)).z for c in floor.bound_box)
changes=[]
for o in list(bpy.data.objects):
    key=o.get('program_key','')
    if key.endswith('bedroom2_nightstand') and o.location.y<10:
        o.location.y+=.13;changes.append({'object':o.name,'move_y':.13})
    if key.endswith('living_media'):
        loc=o.location.copy();yaw=o.rotation_euler.z;scale=o.scale.copy();unit=key.split('_')[0]
        bpy.data.objects.remove(o,do_unlink=True)
        factory=ph.MediaWallFactory(48712503);factory.W=2.8
        new=factory.spawn_asset(900+int(unit));new.location=loc;new.rotation_euler.z=yaw;new.scale=scale
        new.name=f'Residential03_{key}';new['program_key']=key;new['reference_scene_owner']='dual_unit_residential_floor_03';new['audit_kind']='furniture'
        changes.append({'object':new.name,'actual_width_m':2.8})
    elif key.endswith('_wc') and o.type=='MESH':
        bpy.context.view_layer.update();bottom=min((o.matrix_world@Vector(c)).z for c in o.bound_box);o.location.z+=fz-bottom
# Shared core uses stone, not residential oak, consistent with source imagery.
from room_planner import proc_assets as pa
stone=pa._flat('res03_shared_core_stone',(.52,.51,.48),.55)
mapping=json.loads((ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/room_mapping.json').read_text())
for key in ['shared_entrance','elevator','shared_landing','stairs','lift_bypass']:
    floor=bpy.data.objects[mapping[key]['room_id']+'.floor'];floor.data.materials.clear();floor.data.materials.append(stone)
out=base/'scene_candidate_r2.blend';bpy.ops.wm.save_as_mainfile(filepath=str(out))
(base/'correction_r2.json').write_text(json.dumps({'source':'scene_candidate_r1.blend','changes':changes,'visual_acceptance':False},indent=2))
