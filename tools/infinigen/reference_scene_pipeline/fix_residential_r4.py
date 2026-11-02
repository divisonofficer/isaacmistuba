"""Repair measured door approaches and provide actual stairwell headroom."""
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector
from cut_surface import remove_box_faces
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'))
base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full'
ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r3.blend'))
floor=bpy.data.objects['bedroom_0/0.floor'];fz=max((floor.matrix_world@Vector(c)).z for c in floor.bound_box)
cz=2.69
changes=[]
for o in bpy.data.objects:
    key=o.get('program_key','')
    if not key.startswith(('101_','102_')):continue
    unit=int(key[:3]);suffix=key[4:]
    pose=None
    if suffix=='dressing':pose=(3.5,12.15,math.pi/2)
    elif suffix=='bathroom1_vanity':pose=(5.70,12.15,math.pi/2)
    elif suffix=='bathroom1_shower':pose=(5.62,13.38,math.pi)
    elif suffix=='bathroom1_wc':pose=(6.50,13.50,-math.pi/2)
    elif suffix=='bedroom3_wardrobe':pose=(4.75,1.12,math.pi)
    if pose:
        x,y,yaw=pose;o.location.x=21.5-x if unit==102 else x;o.location.y=y;o.rotation_euler.z=math.pi-yaw if unit==102 else yaw
        changes.append({'object':o.name,'key':key,'pose':list(o.location),'yaw':o.rotation_euler.z})

mapping=json.loads((ref/'room_mapping.json').read_text());room=mapping['stairs']['room_id']
shell=bpy.data.objects.get(room+'.exterior')
if shell:remove_box_faces(shell,(10.75,14.5,2.75),(3.1,6.55,.70))
dark=bpy.data.materials['res03_charcoal'];white=bpy.data.materials['res03_plaster']
def box(key,loc,size,mat,cutaway=True):
    bpy.ops.mesh.primitive_cube_add(size=1,location=loc);o=bpy.context.object;o.name='Residential03_r4_'+key;o.dimensions=size
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(mat)
    o['reference_scene_owner']='dual_unit_residential_floor_03';o['program_key']=key;o['audit_kind']='architecture'
    o['reference_ceiling_detail']=cutaway;return o
for x in (9.04,12.46):box('upper_stair_shaft_wall',(x,14.5,4.15),(.12,7,2.9),white)
box('upper_stair_shaft_back',(10.75,17.96,4.15),(3.5,.12,2.9),white)
box('upper_stair_shaft_cap',(10.75,14.5,5.62),(3.5,7,.10),white)
for o in list(bpy.data.objects):
    if o.get('program_key')=='stairs_ceiling_fixture':bpy.data.objects.remove(o,do_unlink=True)
light=bpy.data.objects.get('res03_area_stairs')
if light:
    light.location=(9.22,13.5,fz+1.9);light.rotation_euler=(0,-math.pi/2,0);light.data.energy=120
box('stair_wall_sconce',(9.145,13.5,fz+1.9),(.065,.30,.40),white,False)

# Measured upward rays at every tread's centre verify the real native cap was
# removed; any remaining headroom issue is a failure, not a cosmetic pass.
bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();rays=[]
for o in bpy.data.objects:
    if o.get('audit_kind')!='stair_tread' or 'tread' not in o.get('program_key',''):continue
    pts=[o.matrix_world@Vector(c) for c in o.bound_box];center=sum(pts,Vector())/8;top=max(v.z for v in pts)
    h,p,n,i,hit,m=bpy.context.scene.ray_cast(deps,Vector((center.x,center.y,top+.01)),Vector((0,0,1)),distance=6)
    clearance=p.z-top if h else None
    rays.append({'tread':o.name,'clearance_m':clearance,'hit':hit.name if h else None,'pass':clearance is None or clearance>=2.0})
out=base/'scene_candidate_r4.blend';bpy.ops.wm.save_as_mainfile(filepath=str(out))
(ref/'stair_headroom_r4.json').write_text(json.dumps({'source':str(out),'rays':rays,'all_pass':all(r['pass'] for r in rays),'scope':'vertical rays at tread centres only; not complete swept-body stair certification'},indent=2))
(base/'correction_r4.json').write_text(json.dumps({'poses':changes,'stair_shaft':'opened actual native cap and extended headroom volume','visual_acceptance':False},indent=2))
