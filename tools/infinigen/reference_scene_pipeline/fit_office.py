"""Deterministic first candidate using the production Infinigen prop factories.

World poses are authored from the source, not sampled until a render happens to
look good. Every spawned object's actual dimensions and floor support are saved.
"""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
from room_planner import proc_office as po
from room_planner import proc_home as ph
from room_planner.realize import _cls
from cut_surface import remove_box_faces

ap=argparse.ArgumentParser();ap.add_argument('blend');ap.add_argument('--out',required=True)
a=ap.parse_args();bpy.ops.wm.open_mainfile(filepath=str(Path(a.blend).resolve()))
pa.STYLE.update(desk_style='oak',task_chair_style='mesh',kitchen_front='oak',
                desk_top_rgb=[.62,.46,.30])
pa._ROOM_PICK['task_chair']=(.10,.16,.23)
added=[]
floors=[o for o in bpy.data.objects if o.name.endswith('.floor')]
fz=max((floors[0].matrix_world@Vector(c)).z for c in floors[0].bound_box)
ceiling_z=min(min((o.matrix_world@Vector(c)).z for c in o.bound_box)
              for o in bpy.data.objects if o.name.endswith('.ceiling'))
def spawn(cls,key,x,y,yaw=0,**attrs):
    fac=cls(48712502+len(added))
    for k,v in attrs.items():setattr(fac,k,v)
    o=fac.spawn_asset(len(added));o.name='Office02_'+key+'_'+o.name
    o.rotation_euler.z=yaw;o.location=(x,y,fz);bpy.context.view_layer.update()
    bottom=min((o.matrix_world@Vector(c)).z for c in o.bound_box)
    o.location.z+=fz-bottom
    o['reference_scene_owner']='commercial_office_floor_02';o['program_key']=key
    added.append(o);return o

dark=pa._flat('office02_charcoal',(.025,.03,.035),.4)
glass=pa._flat('office02_partition_glass',(.94,.97,.99),.04,transmission=1)
white=pa._flat('office02_white',(.82,.82,.79),.8)
def cube(name,xyz,size,mat):
    bpy.ops.mesh.primitive_cube_add(size=1,location=xyz);o=bpy.context.object
    o.name='Office02_'+name;o.dimensions=size
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    o.data.materials.append(mat);return o

# Actual wall cutouts retain structural heads and sills; leave native doors.
walls=[o for o in bpy.data.objects if o.type=='MESH' and o.name.endswith(('.wall','.exterior'))]
cuts=[(4,3.1+i*2.5,5.4+i*2.5,'vertical') for i in range(6)]
cuts += [(18,.95,5.85,'horizontal'),(18,6.15,9.85,'horizontal'),(18,10.15,14.4,'horizontal')]
for idx,(axis,lo,hi,orient) in enumerate(cuts):
    # Do not fill a doorway with a new glass panel: subtract the authored door
    # interval from glazing and frame around each surviving fixed pane.
    if orient=='vertical':
        lo=max(lo,3+idx*2.5+1.43)
        center=(axis,(lo+hi)/2,fz+1.42);size=(.65,hi-lo,2.40)
    else:
        # Northern door openings are at 4.3..5.3 / 7..8 / 11..12.
        center=((lo+hi)/2,axis,fz+1.42);size=(hi-lo,.65,2.40)
    for wall in walls:
        pts=[wall.matrix_world@Vector(c) for c in wall.bound_box]
        if all(max(v[k] for v in pts)>=center[k]-size[k]/2 and min(v[k] for v in pts)<=center[k]+size[k]/2 for k in range(3)):
            remove_box_faces(wall,center,size)
    spans=[(lo,hi)]
    if orient=='horizontal':
        da,db=[(4.3,5.3),(7,8),(11,12)][idx-6]
        spans=[(lo,da-.08),(db+.08,hi)]
    for j,(p,q) in enumerate(spans):
        if q-p<.12:continue
        xy=(axis,(p+q)/2) if orient=='vertical' else ((p+q)/2,axis)
        dims=(.012,q-p,2.38) if orient=='vertical' else (q-p,.012,2.38)
        cube(f'glazing_{idx}_{j}',(*xy,fz+1.42),dims,glass)
        for end in (p,q):
            pos=(axis,end) if orient=='vertical' else (end,axis)
            cube(f'glazing_mullion_{idx}_{j}',(*pos,fz+1.42),(.045,.045,2.46),dark)
        for z in (.20,2.64):
            dims=(.045,q-p,.045) if orient=='vertical' else (q-p,.045,.045)
            cube(f'glazing_rail_{idx}_{j}',(*xy,fz+z),dims,dark)

for i in range(6):
    y=4.25+i*2.5
    spawn(pa.OfficeDeskFactory,f'private_{i+1}_desk',1.65,y,0,L=1.4,D=.78)
    spawn(pa.TaskChairFactory,f'private_{i+1}_chair',2.5,y,math.pi)
    spawn(pa.FilingCabinetFactory,f'private_{i+1}_storage',3.45,y+.65,math.pi)

# Six four-seat pods with explicit aisles; actual reference is a cluster layout.
for col,x in enumerate((6.0,11.9)):
    for row,y in enumerate((11.7,15.1)):
        desk=spawn(po.DeskBenchFactory,f'pod_{col}_{row}',x,y,math.pi/2,N=2)
        for k,(sx,sy,yaw) in enumerate(desk['seats']):
            pos=desk.matrix_world@Vector((sx,sy,0))
            spawn(pa.TaskChairFactory,f'pod_{col}_{row}_chair{k}',pos.x,pos.y,yaw+math.pi/2)
for row,y in enumerate((5.2,8.4)):
    desk=spawn(po.DeskBenchFactory,f'pod_lower_{row}',6.8,y,math.pi/2,N=2)
    for k,(sx,sy,yaw) in enumerate(desk['seats']):
        pos=desk.matrix_world@Vector((sx,sy,0))
        spawn(pa.TaskChairFactory,f'pod_lower_{row}_chair{k}',pos.x,pos.y,yaw+math.pi/2)

for key,x,L in [('conference_a',3.4,2.8),('meeting_b',8,1.8),('meeting_c',12.1,1.8)]:
    spawn(pa.ConferenceTableFactory,key+'_table',x,20,math.pi/2,L=L,W=1.0)
    for side in (-1,1):
        for dx in (-.6,.6):spawn(pa.TaskChairFactory,key+f'_chair_{side}_{dx}',x+dx,20+side*.95,-side*math.pi/2)

spawn(pa.ReceptionDeskFactory,'reception_desk',3.2,1.55,-math.pi/2)
spawn(pa.TaskChairFactory,'reception_staff',3.2,2.45,-math.pi/2)
spawn(_cls('proc:UpholsteredBenchFactory'),'waiting_bench',8.8,1.55,math.pi,n=2)
spawn(ph.HomeKitchenRunFactory,'breakout_kitchen_run',14.6,5.2,math.pi,L=3.6)
spawn(pa.ConferenceTableFactory,'breakout_table',12.3,2.0,math.pi/2,L=2.2,W=1.0)
for side in (-1,1):
    for dx in (-.6,.6):spawn(pa.TaskChairFactory,f'breakout_chair_{side}_{dx}',12.3+dx,2+side*.95,-side*math.pi/2)
for key,x,y in [('support_west',11.3,9.5),('support_east',14.65,8.8)]:
    spawn(pa.FilingCabinetFactory,key+'_storage',x,y,math.pi)

# Native generated plant library, preserved as actual geometry.
library=sorted((ROOT/'data/plant_library').glob('plant_*.blend'))
for i,(x,y) in enumerate([(1.1,1),(9.3,1.2),(14.3,16.7),(5,17),(13.7,7.3)]):
    if not library:break
    with bpy.data.libraries.load(str(library[i%len(library)]),link=False) as (src,dst):dst.objects=[n for n in src.objects if n=='ir_plant']
    for o in dst.objects:
        if o:
            bpy.context.scene.collection.objects.link(o);o.location=(x,y,fz);o.name=f'Office02_native_plant_{i}'

import os
os.environ.update(ROOM_FLOOR_CARPET='.42,.44,.46',ROOM_CARPET_ROOMS='office,utility,hallway',ROOM_CARPET_STREAK='.12',ROOM_CARPET_VARY='.04')
import carpet_floor
stats={};carpet_floor.apply(stats)
for o in floors:
    if o.name.startswith('hallway'):
        oak=pa._flat('office02_reception_oak',(.48,.35,.22),.55,wood=True)
        o.data.materials.clear();o.data.materials.append(oak)

# Explicit ceiling and evenly distributed practical fixtures, independent of
# window-energy randomness. Cutaway renderer hides only ceiling slabs.
for o in bpy.data.objects:
    if o.name.endswith('.ceiling'):
        o.data.materials.clear();o.data.materials.append(white)
for x,y in [(2,1.5),(7,1.5),(12,3.5),(12,6.5),(6.5,5),(6.5,8.5),(6.5,12),(6.5,15.5),(12.5,12),(12.5,15.5),(3,20),(8,20),(12,20)]+[(2,4.25+i*2.5) for i in range(6)]:
    lamp=cube('linear_fixture',(x,y,ceiling_z-.035),(.12,1.3,.055),white)
    data=bpy.data.lights.new('office02_area','AREA');data.energy=95;data.shape='RECTANGLE';data.size=.5;data.size_y=1.3
    obj=bpy.data.objects.new(data.name,data);bpy.context.scene.collection.objects.link(obj);obj.location=(x,y,ceiling_z-.09)

bpy.context.scene['reference_scene_id']='commercial_office_floor_02'
out=Path(a.out).resolve();bpy.ops.wm.save_as_mainfile(filepath=str(out))
receipt={'floor_z':fz,'measured_ceiling_z':ceiling_z,'candidate':str(out),'status':'candidate_visual_review_pending','carpet':stats,
         'furniture':[{'name':o.name,'key':o['program_key'],'location':list(o.location),'dimensions':list(o.dimensions)} for o in added]}
out.with_suffix('.fitout.json').write_text(json.dumps(receipt,indent=2))
print('OFFICE_FITOUT',len(added),flush=True)
