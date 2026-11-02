"""Resolve r6 vegetation clearance and fitted cabinetry construction."""
import json
from pathlib import Path
import sys
import bpy
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r6.blend'))
fz=max((bpy.data.objects['office_0/9.floor'].matrix_world@Vector(c)).z for c in bpy.data.objects['office_0/9.floor'].bound_box)
oak=bpy.data.materials['office02_reference_warm_oak'];dark=bpy.data.materials['office02_accessory_dark']
paper=pa._flat('office02_office_paper',(.8,.79,.74),.85)
changes=[]
def box(key,xyz,size,mat,kind='fixture'):
    bpy.ops.mesh.primitive_cube_add(size=1,location=xyz);o=bpy.context.object;o.dimensions=size;o.name='Office02_r7_'+key
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(mat)
    o['reference_scene_owner']='commercial_office_floor_02';o['program_key']=key;o['audit_kind']=kind;return o
for index,xy in [(1,(9.4,.45)),(4,(13.10,7.30))]:
    plant=bpy.data.objects[f'Office02_native_plant_{index}'];delta=Vector((xy[0]-plant.location.x,xy[1]-plant.location.y,0))
    for o in bpy.data.objects:
        if o.get('program_key') in (f'plant_{index}',f'pot_{index}',f'soil_{index}'):o.location+=delta
    changes.append({'plant':index,'delta':list(delta)})
for o in list(bpy.data.objects):
    if o.get('program_key')=='coffee_base':bpy.data.objects.remove(o,do_unlink=True)
    elif o.get('program_key') in ('coffee_cabinet_front','coffee_pull') and o.location.y<4.10:bpy.data.objects.remove(o,do_unlink=True)
# Hollow cabinet shell keeps the real sink basin unobstructed and reserves an
# actual fridge bay. Support surfaces are real geometry, not dark overlays.
for y in [3.415,6.885]:box('coffee_end_panel',(14.275,y,fz+.43),(.65,.03,.86),oak)
box('coffee_back_panel',(14.585,5.15,fz+.43),(.03,3.5,.86),oak)
box('coffee_bottom_panel',(14.275,5.15,fz+.08),(.62,3.44,.035),oak)
box('coffee_plinth',(14.32,5.15,fz+.04),(.52,3.40,.08),dark,'furniture')
fridge=next(o for o in bpy.data.objects if o.get('program_key')=='coffee_fridge');fridge.location.z=fz+.5075
box('fridge_door_handle',(13.905,3.55,fz+.72),(.025,.20,.02),dark)
# Complete support-room fit-out without inventing room functions unreadable in
# the source: modest archive shelves, binders and paper stock.
for key,x,y in [('west',11.25,9.70),('east',14.25,8.29)]:
    for z in (1.35,1.85):
        shelf=box(key+'_wall_shelf',(x,y,fz+z),(1.15,.30,.035),oak)
        for dx in (-.42,.42):box(key+'_shelf_bracket',(x+dx,y,fz+z-.14),(.025,.24,.25),dark)
        for i in range(6):
            box(key+'_archive_binder',(x-.43+i*.15,y,fz+z+.16),(.095,.22,.28),dark if i%2 else oak)
            box(key+'_binder_label',(x-.43+i*.15,y+(.115 if key=='east' else -.115),fz+z+.19),(.055,.003,.07),paper)
    cabinet=next(o for o in bpy.data.objects if o.get('program_key')==f'support_{key}_storage')
    pts=[cabinet.matrix_world@Vector(v) for v in cabinet.bound_box];top=max(v.z for v in pts)
    box(key+'_paper_stack',(cabinet.location.x,cabinet.location.y,top+.026),(.28,.20,.05),paper)
out=base/'scene_candidate_r7.blend';bpy.ops.wm.save_as_mainfile(filepath=str(out))
(base/'correction_r7.json').write_text(json.dumps({'changes':changes,'sink_cabinet':'hollow_shell','support_rooms':'generic archive fitout; source labels uncertain','visual_acceptance':False},indent=2))
