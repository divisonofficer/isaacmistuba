"""Clear native exterior face shells behind glass; normalize casing finish."""
import json
from pathlib import Path
import sys
import bpy
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r2.blend'))
dark=pa._flat('office02_casing_charcoal',(.025,.03,.035),.45)
for o in bpy.data.objects:
    if o.type=='MESH' and 'DoorCasingFactory' in o.name:
        for slot in o.material_slots:slot.material=dark
exteriors=[o for o in bpy.data.objects if o.type=='MESH' and o.name.endswith('.exterior')]
cuts=[]
for i in range(6):cuts.append(((4,4.915+i*2.5,1.53),(.65,.97,2.4)))
for lo,hi in [(.95,5.85),(6.15,9.85),(10.15,14.4)]:cuts.append((((lo+hi)/2,18,1.53),(hi-lo,.65,2.4)))
changes=[]
for index,(loc,size) in enumerate(cuts):
    bpy.ops.mesh.primitive_cube_add(size=1,location=loc);c=bpy.context.object;c.dimensions=size
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    for wall in exteriors:
        pts=[wall.matrix_world@Vector(v) for v in wall.bound_box]
        if all(max(v[k] for v in pts)>=loc[k]-size[k]/2 and min(v[k] for v in pts)<=loc[k]+size[k]/2 for k in range(3)):
            bpy.context.view_layer.objects.active=wall
            m=wall.modifiers.new('unseal_reference_glass','BOOLEAN');m.operation='DIFFERENCE';m.solver='EXACT';m.object=c
            bpy.ops.object.modifier_apply(modifier=m.name);changes.append(wall.name)
    bpy.data.objects.remove(c,do_unlink=True)
out=base/'scene_candidate_r3.blend';bpy.ops.wm.save_as_mainfile(filepath=str(out))
(base/'correction_r3.json').write_text(json.dumps({'reason':'Ray stack identified native exterior shell sealing glass opening','changed_exteriors':changes,'visual_acceptance':False},indent=2))
