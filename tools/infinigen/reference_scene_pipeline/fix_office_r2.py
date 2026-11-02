"""Fix first-review defects from measured ceiling geometry, not assumed height."""
import json
from pathlib import Path
import sys
import bpy
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
sys.path.insert(0,str(Path(__file__).resolve().parent))
from native_component_materials import assign_door_body_preserving_hardware
base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r1.blend'))
ceilings=[o for o in bpy.data.objects if o.name.endswith('.ceiling')]
ceiling=min(min((o.matrix_world@Vector(v)).z for v in o.bound_box) for o in ceilings)
records=[]
for o in bpy.data.objects:
    if o.type=='LIGHT' and o.name.startswith('office02_area'):
        old=o.location.z;o.location.z=ceiling-.09;o.data.energy=150
        records.append({'object':o.name,'before_z':old,'after_z':o.location.z})
    if o.name.startswith('Office02_linear_fixture'):
        o.location.z=ceiling-.035
        for material in o.data.materials:
            if material and material.use_nodes:
                # Copy fixture material so ceiling plaster does not emit.
                local=material.copy();o.data.materials.clear();o.data.materials.append(local)
                bs=local.node_tree.nodes.get('Principled BSDF')
                if bs:
                    bs.inputs['Emission Color'].default_value=(1,.94,.84,1)
                    bs.inputs['Emission Strength'].default_value=2
                break
oak=pa._flat('office02_door_oak',(.47,.33,.19),.55,wood=True)
door_material_records=[]
for o in bpy.data.objects:
    if o.type=='MESH' and 'DoorFactory' in o.name:
        door_material_records.append(assign_door_body_preserving_hardware(o,oak))
out=base/'scene_candidate_r2.blend';bpy.ops.wm.save_as_mainfile(filepath=str(out))
(base/'correction_r2.json').write_text(json.dumps({'reason':'r1 lights were above measured ceiling','measured_ceiling_z':ceiling,'changes':records,'native_door_body_material_changes':door_material_records,'visual_acceptance':False},indent=2))
