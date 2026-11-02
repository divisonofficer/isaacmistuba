"""Fixed source-based furnishing for two mirrored apartments; no planner API."""
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector
from shapely.geometry import Polygon
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'))
sys.path.insert(0,str(Path(__file__).parent))
from native_component_materials import assign_door_body_preserving_hardware
from wc_layout_checks import calibrate_seat_height, place_bathroom2_wc
from wetroom_layout_helpers import place_bottom_wall_vanity, place_sidewall_wc
from room_planner import proc_assets as pa
from room_planner import proc_home as ph
from room_planner.realize import _cls
base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full'
ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
assert not (base/'scene_candidate_r1.blend').exists(), 'Preserve existing candidate;initial fitout is not an in-place rerender.'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_mat2.blend'))
mapping=json.loads((ref/'room_mapping.json').read_text())
floor=bpy.data.objects['bedroom_0/0.floor'];fz=max((floor.matrix_world@Vector(c)).z for c in floor.bound_box)
cz=min(min((o.matrix_world@Vector(c)).z for c in o.bound_box) for o in bpy.data.objects if o.name.endswith('.ceiling'))
oak=pa._flat('res03_oak',(.48,.34,.21),.5,wood=True)
white=pa._flat('res03_plaster',(.83,.81,.76),.8)
dark=pa._flat('res03_charcoal',(.025,.03,.035),.4)
metal=pa._flat('res03_lift_steel',(.43,.46,.48),.3,metallic=.9)
stone=pa._flat('res03_stone',(.56,.54,.49),.6)
added=[]
def box(key,loc,size,mat,kind='fixture'):
    bpy.ops.mesh.primitive_cube_add(size=1,location=loc);o=bpy.context.object;o.name='Residential03_'+key;o.dimensions=size
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(mat)
    o['reference_scene_owner']='dual_unit_residential_floor_03';o['program_key']=key;o['audit_kind']=kind;added.append(o);return o
def spawn(cls,key,x,y,yaw=0,unit=101,**attrs):
    fac=cls(48712503+len(added))
    for k,v in attrs.items():setattr(fac,k,v)
    o=fac.spawn_asset(len(added));o.name=f'Residential03_{unit}_{key}_'+o.name
    o.rotation_euler.z=yaw;o.location=(x,y,fz)
    # Mirror actual mesh and pose together; do not rotate an asymmetric sofa
    # into the wrong corner of unit102.
    if unit==102:o.location.x=21.5-x;o.rotation_euler.z=math.pi-yaw;o.scale.y*=-1
    bpy.context.view_layer.update();low=min((o.matrix_world@Vector(c)).z for c in o.bound_box);o.location.z+=fz-low
    o['reference_scene_owner']='dual_unit_residential_floor_03';o['program_key']=f'{unit}_{key}';o['audit_kind']='furniture';added.append(o)
    return o
pa.STYLE.update(bed_width_m=1.6,kitchen_front='oak',upholstery_srgb=[.67,.66,.59])
toilet_class=_cls('inf:ToiletFactory')
toilet_proto=None
for unit in (101,102):
    colors=[(.10,.22,.25),(.27,.32,.20),(.55,.38,.32)] if unit==101 else [(.50,.33,.27),(.43,.27,.32),(.40,.45,.30)]
    for i,(name,x,y,yaw) in enumerate([('master',7,17.55,-math.pi/2),('bedroom2',.35,10.7,0),('bedroom3',.35,1.45,0)]):
        spawn(ph.SoftBedFactory,name+'_bed',x,y,yaw,unit,throw_rgb=colors[i])
        # Nightstands remain a separate real supported mesh, not decorations.
        for side in (-1,1):
            if name=='master':nx,ny=x+side*1.22,y-.25
            else:nx,ny=x+.25,y+side*.98
            mx=21.5-nx if unit==102 else nx
            box(f'{unit}_{name}_nightstand',(mx,ny,fz+.27),(.40,.35,.54),oak,'furniture')
    spawn(ph.SectionalSofaFactory,'living_sectional',.35,7.75,0,unit)
    spawn(ph.StoneCoffeeTableFactory,'living_coffee_table',3.25,7.5,0,unit)
    spawn(ph.MediaWallFactory,'living_media',6.75,7.5,math.pi,unit)
    spawn(ph.HomeKitchenRunFactory,'kitchen_run',8.7,4.5,math.pi,unit,L=2.5)
    spawn(ph.StoneDiningTableFactory,'dining_table',4.8,4.65,math.pi/2,unit,L=1.7)
    for side in (-1,1):
        for dx in (-.48,.48):spawn(ph.WhiteDiningChairFactory,f'dining_chair_{side}_{dx}',4.8+dx,4.65+side*.90,-side*math.pi/2,unit)
    spawn(ph.OpenWardrobeFactory,'dressing',2.15,13.5,0,unit)
    spawn(ph.OakWardrobeFactory,'bedroom3_wardrobe',4.75,1.5,math.pi,unit,L=1.5)
    spawn(ph.BalconyTableFactory,'balcony_table',2.5,16.5,0,unit)
    for angle in (0,math.pi/2,math.pi,3*math.pi/2):
        spawn(ph.BalconyChairFactory,f'balcony_chair_{angle}',2.5+1.05*math.cos(angle),16.5+1.05*math.sin(angle),angle+math.pi,unit)
    # Eight explicitly allocated wet rooms across the two units; each has a
    # real WC, basin and shower. Roles/labels remain reconstruction assumptions.
    for name,x0,y0,x1,y1 in [('ensuite',0,12,2,15),('bathroom1',5,12,7,14),('bathroom2',0,3,3,6),('laundry_wc',5,0,7,3)]:
        vanity=spawn(ph.HomeVanityFactory,name+'_vanity',x0+.15,y0+.75,0,unit)
        if name in ('ensuite','laundry_wc'):place_bottom_wall_vanity(vanity,mapping[f'{unit}_{name}']['polygon_m'],unit)
        spawn(ph.ShowerEnclosureFactory,name+'_shower',x1-.62,y1-.62,math.pi,unit)
        if toilet_proto is None:
            o=spawn(toilet_class,name+'_wc',x1-.52,y0+.65,math.pi,unit);toilet_proto=o
            bpy.context.view_layer.update()
            # Enforce plausible bowl size on the reusable native model.
            scale=min(1.0,.68/max(o.dimensions.x,.01),.46/max(o.dimensions.y,.01));o.scale*=scale
        else:
            o=toilet_proto.copy();o.data=toilet_proto.data.copy();bpy.context.scene.collection.objects.link(o)
            o.name=f'Residential03_{unit}_{name}_wc';o.location=(21.5-(x1-.52) if unit==102 else x1-.52,y0+.65,fz)
            o.rotation_euler.z=0 if unit==102 else math.pi
            if unit==102 and o.scale.y>0:o.scale.y*=-1
            bpy.context.view_layer.update();lo=min((o.matrix_world@Vector(c)).z for c in o.bound_box);o.location.z+=fz-lo
            o['program_key']=f'{unit}_{name}_wc';added.append(o)
        # Native overall/open-lid bounds do not certify seat height or entry clearance.
        calibrate_seat_height(o,.42,floor_z=fz)
        if name=='bathroom2':place_bathroom2_wc(o,mapping[f'{unit}_bathroom2']['polygon_m'])
        elif name in ('ensuite','laundry_wc'):place_sidewall_wc(o,mapping[f'{unit}_{name}']['polygon_m'],unit)

# A physical switchback stair: two flights, intermediate landing, side rails.
stair_x=(9.90,11.60);start_y=11.65;pitch=.29;rise=.15
for k in range(9):
    box('stair_lower_tread',(stair_x[0],start_y+(k+.5)*pitch,fz+(k+1)*rise-.04),(1.10,pitch,.08),stone,'stair_tread')
    box('stair_upper_tread',(stair_x[1],start_y+(8-k+.5)*pitch,fz+1.35+(k+1)*rise-.04),(1.10,pitch,.08),stone,'stair_tread')
box('stair_half_landing',(10.75,14.8,fz+1.31),(2.8,1.1,.08),stone,'stair_tread')
for x in (9.3,10.5,11.0,12.2):
    for k in range(9):
        y=start_y+(k+.5)*pitch;z=fz+(k+1)*rise if x<10.8 else fz+1.35+(9-k)*rise
        box('stair_guard_post',(x,y,z+.46),(.025,.025,.92),dark,'stair_guard')
# Lift doors face the bypass, clear of the corridor and never used as a route.
for o in list(bpy.data.objects):
    if o.type=='MESH' and 'DoorFactory' in o.name:
        c=sum((o.matrix_world@Vector(v) for v in o.bound_box),Vector())/8
        if abs(c.x-11)<.6 and 2.7<c.y<4.3:bpy.data.objects.remove(o,do_unlink=True)
for y in (3.25,3.75):box('lift_door',(11.025,y,fz+1.10),(.045,.49,2.20),metal,'lift_door')
for y in (2.98,4.02):box('lift_jamb',(11.04,y,fz+1.13),(.08,.06,2.26),metal)
box('lift_header',(11.04,3.5,fz+2.27),(.08,1.10,.08),metal)
box('lift_call_panel',(11.09,4.3,fz+1.2),(.04,.12,.27),dark)

# Measured ceiling and a fixture in every actual authored room. This includes
# small wet rooms and closets, which cannot borrow light through opaque walls.
for key,r in mapping.items():
    center=Polygon(r['polygon_m']).representative_point();x,y=center.x,center.y
    floor_obj=bpy.data.objects.get(r['room_id']+'.floor')
    ceiling=bpy.data.objects.get(r['room_id']+'.ceiling')
    ceiling_z=min((ceiling.matrix_world@Vector(c)).z for c in ceiling.bound_box) if ceiling else cz
    if ceiling:ceiling.data.materials.clear();ceiling.data.materials.append(white)
    fixture=box(key+'_ceiling_fixture',(x,y,ceiling_z-.04),(.42,.42,.04),white,'ceiling_fixture');fixture['reference_ceiling_detail']=True
    data=bpy.data.lights.new('res03_area_'+key,'AREA');data.energy=70 if 'bath' in key else 125;data.shape='DISK';data.size=.7
    obj=bpy.data.objects.new(data.name,data);bpy.context.scene.collection.objects.link(obj);obj.location=(x,y,ceiling_z-.10)
door_material_records=[]
for o in bpy.data.objects:
    if o.type=='MESH' and 'DoorCasingFactory' in o.name:
        for slot in o.material_slots:slot.material=dark
    elif o.type=='MESH' and 'DoorFactory' in o.name:
        try:
            door_material_records.append(assign_door_body_preserving_hardware(o,oak))
        except ValueError as error:
            # Preserve original materials when native tags cannot safely identify the body.
            door_material_records.append({'object':o.name,'status':'unchanged_requires_manual_finish','reason':str(error)})
out=base/'scene_candidate_r1.blend';bpy.ops.wm.save_as_mainfile(filepath=str(out))
(base/'scene_candidate_r1.fitout.json').write_text(json.dumps({'source':'scene_mat2.blend','status':'candidate_visual_review_pending','floor_z':fz,'ceiling_z':cz,'objects':len(added),'bedroom_count':6,'room_count':len(mapping),'unverified':['Stair support/guard continuity','Bathroom clearance and fixture door arcs','Balcony facade refinement','Reference detail and visual similarity']},indent=2))
(ref/'initial_native_door_material_changes.json').write_text(json.dumps(door_material_records,indent=2))
print('RESIDENTIAL_FITOUT',len(added),flush=True)
