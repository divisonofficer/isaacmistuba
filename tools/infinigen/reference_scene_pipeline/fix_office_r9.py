"""Close the visible top fascia gap identified in the complete r8 review."""
from pathlib import Path
import json
import bpy
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r8.blend'))
floor=bpy.data.objects['office_0/9.floor'];fz=max((floor.matrix_world@Vector(c)).z for c in floor.bound_box)
bpy.ops.mesh.primitive_cube_add(size=1,location=(13.941,5.15,fz+.853));o=bpy.context.object;o.name='Office02_r9_coffee_fascia';o.dimensions=(.025,3.5,.067)
bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(bpy.data.materials['office02_reference_warm_oak'])
o['reference_scene_owner']='commercial_office_floor_02';o['program_key']='coffee_top_fascia';o['audit_kind']='fixture'
out=base/'scene_candidate_r9.blend';bpy.ops.wm.save_as_mainfile(filepath=str(out))
(base/'correction_r9.json').write_text(json.dumps({'source':'scene_candidate_r8.blend','change':'physical oak fascia closes 6 cm front gap below worktop; sink aperture unchanged','visual_acceptance':False},indent=2))
