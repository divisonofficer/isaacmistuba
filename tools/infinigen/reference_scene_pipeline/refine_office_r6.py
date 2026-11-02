"""Batch all r5 direct-review corrections before the next review render."""
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
from room_planner.proc_home import WhiteDiningChairFactory,OakCredenzaFactory
base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r5.blend'))
fz=max((bpy.data.objects['office_0/9.floor'].matrix_world@Vector(c)).z for c in bpy.data.objects['office_0/9.floor'].bound_box)
cz=min(min((o.matrix_world@Vector(c)).z for c in o.bound_box) for o in bpy.data.objects if o.name.endswith('.ceiling'))
pa.STYLE.update(upholstery_srgb=[.15,.23,.30])
oak=pa._flat('office02_reference_warm_oak',(.46,.31,.18),.5,wood=True)
stone=pa._flat('office02_reference_worktop',(.8,.79,.74),.3)
dark=pa._flat('office02_accessory_dark',(.025,.03,.035),.4)
steel=pa._flat('office02_sink_steel',(.55,.6,.64),.25,metallic=.9)
soil=pa._flat('office02_planter_soil',(.055,.035,.018),1)
ceramic=pa._flat('office02_planter_ceramic',(.48,.48,.44),.8)
all_new=[]
def mark(o,key,kind='fixture'):
    o.name='Office02_r6_'+key;o['reference_scene_owner']='commercial_office_floor_02';o['program_key']=key;o['audit_kind']=kind;all_new.append(o);return o
def box(key,loc,size,material,kind='fixture'):
    bpy.ops.mesh.primitive_cube_add(size=1,location=loc);o=bpy.context.object;o.dimensions=size
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(material);mark(o,key,kind);return o
def cyl(key,loc,radius,depth,material,kind='fixture'):
    bpy.ops.mesh.primitive_cylinder_add(vertices=32,radius=radius,depth=depth,location=loc);o=bpy.context.object;o.data.materials.append(material);mark(o,key,kind)
    for f in o.data.polygons:f.use_smooth=True
    return o
def settle(o):
    bpy.context.view_layer.update();bottom=min((o.matrix_world@Vector(c)).z for c in o.bound_box);o.location.z+=fz-bottom
for o in list(bpy.data.objects):
    if o.type!='MESH':continue
    for slot in o.material_slots:
        name=slot.material.name if slot.material else ''
        if name.startswith(('ir_desk_top','ir_bench_top','ir_conf_top','ir_cred_oak','ir_reception_front')):slot.material=oak
    key=o.get('program_key','')
    if key.startswith(('conference_a_chair','meeting_b_chair','meeting_c_chair','breakout_chair')):
        loc=o.location.copy();yaw=o.rotation_euler.z;bpy.data.objects.remove(o,do_unlink=True)
        new=WhiteDiningChairFactory(48712502+len(all_new)).spawn_asset(len(all_new));new.location=loc;new.rotation_euler.z=yaw;settle(new);mark(new,key,'furniture')

# Six seats at the large meeting table; keep its original camera and table.
for o in list(bpy.data.objects):
    if o.get('program_key','').startswith('conference_a_chair'):bpy.data.objects.remove(o,do_unlink=True)
for side in (-1,1):
    for dx in (-.95,0,.95):
        o=WhiteDiningChairFactory(10+len(all_new)).spawn_asset(len(all_new));o.location=(3.4+dx,20+side*.95,fz);o.rotation_euler.z=-side*math.pi/2;settle(o);mark(o,f'conference_a_chair_{side}_{dx}','furniture')

# All enclosed support spaces have real dedicated lights below their ceilings.
for x,y in [(11.2,8.9),(13.8,8.9)]:
    box('support_ceiling_fixture',(x,y,cz-.035),(.55,.55,.04),stone,'ceiling_fixture')['reference_ceiling_detail']=True
    data=bpy.data.lights.new('office02_support_area','AREA');data.energy=75;data.shape='DISK';data.size=.65
    obj=bpy.data.objects.new(data.name,data);bpy.context.scene.collection.objects.link(obj);obj.location=(x,y,cz-.10)

# Raw plant library meshes have no pots; constrain each crown to its room and
# root it at the soil elevation inside a genuinely hollow ceramic container.
for i,o in enumerate([x for x in bpy.data.objects if x.name.startswith('Office02_native_plant')]):
    bpy.context.view_layer.update();factor=min(1.0,1.4/max(o.dimensions.z,.01),.80/max(o.dimensions.x,o.dimensions.y,.01));o.scale*=factor
    x,y=o.location.x,o.location.y
    if y>7 and y<8:x,y=14.25,7.1
    o.location.x=x;o.location.y=y;bpy.context.view_layer.update()
    bottom=min((o.matrix_world@Vector(c)).z for c in o.bound_box);o.location.z+=fz+.32-bottom
    o['reference_scene_owner']='commercial_office_floor_02';o['program_key']=f'plant_{i}';o['audit_kind']='vegetation'
    n=48;verts=[]
    for r,z in [(.205,fz),(.27,fz+.38),(.238,fz+.38),(.18,fz+.045)]:
        verts.extend([(x+r*math.cos(2*math.pi*k/n),y+r*math.sin(2*math.pi*k/n),z) for k in range(n)])
    faces=[]
    for ring in range(3):
        for k in range(n):faces.append((ring*n+k,ring*n+(k+1)%n,(ring+1)*n+(k+1)%n,(ring+1)*n+k))
    faces.append(tuple(reversed(range(n))));faces.append(tuple(3*n+k for k in range(n)))
    mesh=bpy.data.meshes.new('office02_hollow_pot');mesh.from_pydata(verts,[],faces);mesh.materials.append(ceramic)
    pot=bpy.data.objects.new(f'Office02_r6_pot_{i}',mesh);bpy.context.scene.collection.objects.link(pot);mark(pot,f'pot_{i}','ground_container')
    cyl(f'soil_{i}',(x,y,fz+.315),.225,.025,soil,'soil')

# Replace the domestic stove/hood run with office coffee facilities. The sink
# aperture is built as separate slabs and real recessed basin, not a black decal.
for o in list(bpy.data.objects):
    if o.get('program_key')=='breakout_kitchen_run':bpy.data.objects.remove(o,do_unlink=True)
x0,x1,y0,y1=13.95,14.60,3.4,6.9
box('coffee_base',((x0+x1)/2,(y0+y1)/2,fz+.43),(.65,y1-y0,.86),oak,'furniture')
for k in range(6):
    y=y0+(k+.5)*(y1-y0)/6
    box('coffee_cabinet_front',(x0-.008,y,fz+.44),(.018,(y1-y0)/6-.015,.76),oak)
    box('coffee_pull',(x0-.025,y+.16,fz+.63),(.025,.10,.012),dark)
sa,sb=4.35,4.95
for ya,yb in [(y0,sa),(sb,y1)]:box('coffee_worktop',((x0+x1)/2,(ya+yb)/2,fz+.90),(.69,yb-ya,.035),stone)
for x,w in [(x0+.055,.13),(x1-.055,.13)]:box('sink_rim',(x,(sa+sb)/2,fz+.90),(w,sb-sa,.035),steel)
box('sink_bottom',((x0+x1)/2,(sa+sb)/2,fz+.74),(.40,.54,.02),steel)
for x in [x0+.125,x1-.125]:box('sink_basin_side',(x,(sa+sb)/2,fz+.82),(.015,.54,.16),steel)
for y in [sa+.03,sb-.03]:box('sink_basin_end',((x0+x1)/2,y,fz+.82),(.40,.015,.16),steel)
cyl('tap_stem',(x1-.07,4.65,fz+1.03),.017,.25,steel)
box('tap_spout',(x1-.19,4.65,fz+1.14),(.25,.028,.028),steel)
box('coffee_machine',(14.22,5.65,fz+1.08),(.32,.42,.34),dark)
cyl('coffee_machine_carafe',(14.00,5.65,fz+.99),.07,.14,steel)
for y in [5.25,6.05,6.27]:
    # Hollow mugs with a visible inset interior and a loop handle.
    cyl('mug_body',(14.04,y,fz+.963),.046,.09,stone)
    cyl('mug_interior',(14.04,y,fz+1.009),.036,.002,dark)
box('coffee_upper',(14.48,5.15,fz+1.84),(.26,3.5,.65),oak)
for k in range(6):box('coffee_upper_front',(14.34,3.4+(k+.5)*3.5/6,fz+1.84),(.018,3.5/6-.015,.63),oak)
box('coffee_splash',(14.58,5.15,fz+1.27),(.015,3.5,.69),stone)
box('coffee_fridge',(14.17,3.78,fz+.46),(.50,.65,.82),steel)

# Six small offices get restrained lived-in work objects and low oak storage.
for i in range(6):
    y=4.25+i*2.5
    for old in list(bpy.data.objects):
        if old.get('program_key')==f'private_{i+1}_storage':bpy.data.objects.remove(old,do_unlink=True)
    factory=OakCredenzaFactory(i);factory.L=1.4;cabinet=factory.spawn_asset(len(all_new))
    cabinet.location=(2.1,y+1.10,fz);cabinet.rotation_euler.z=-math.pi/2;settle(cabinet);mark(cabinet,f'private_{i+1}_credenza','furniture')
    box('desk_notebook',(1.87,y+.32,fz+.79),(.18,.24,.025),dark)
    cyl('desk_pen_cup',(1.50,y+.52,fz+.83),.033,.10,stone)
    for off in [-.012,0,.012]:cyl('pen',(1.50+off,y+.52,fz+.90),.003,.13,dark)

out=base/'scene_candidate_r6.blend';bpy.ops.wm.save_as_mainfile(filepath=str(out))
(base/'correction_r6.json').write_text(json.dumps({'source':'scene_candidate_r5.blend','changes':['support room illumination','potted room-contained native vegetation','upholstered meeting/lunch chairs and six-seat conference','warm oak reception/desks','office coffee kitchenette with real recessed sink','private-office storage and accessories'],'new_objects':len(all_new),'visual_acceptance':False},indent=2))
