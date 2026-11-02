"""Batch source/reference finishing and first-review construction corrections."""
import json
import math
import os
from pathlib import Path
import sys
import bpy
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
from room_planner import proc_home as ph
from cut_surface import remove_box_faces
base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full'
ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r2.blend'))
mapping=json.loads((ref/'room_mapping.json').read_text())
floor=bpy.data.objects['bedroom_0/0.floor'];fz=max((floor.matrix_world@Vector(c)).z for c in floor.bound_box)
cz=min(min((o.matrix_world@Vector(c)).z for c in o.bound_box) for o in bpy.data.objects if o.name.endswith('.ceiling'))
oak=bpy.data.materials['res03_oak'];dark=bpy.data.materials['res03_charcoal'];stone=bpy.data.materials['res03_stone']
cream=pa._flat('res03_rug_linen',(.61,.58,.51),.98)
fabric=pa._flat('res03_sheer_linen',(.80,.77,.69),.95,transmission=.08)
glass=pa._flat('res03_living_clear_glass',(.95,.97,.99),.03,transmission=1)
white=bpy.data.materials['res03_plaster']
added=[]
def tag(o,key,kind='fixture'):
    o.name='Residential03_r3_'+key;o['reference_scene_owner']='dual_unit_residential_floor_03';o['program_key']=key;o['audit_kind']=kind;added.append(o);return o
def box(key,loc,size,mat,kind='fixture'):
    bpy.ops.mesh.primitive_cube_add(size=1,location=loc);o=bpy.context.object;o.dimensions=size
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(mat);return tag(o,key,kind)
def rod(key,a,b,r,mat,kind='fixture'):
    a,b=Vector(a),Vector(b);d=b-a;bpy.ops.mesh.primitive_cylinder_add(vertices=20,radius=r,depth=d.length,location=(a+b)/2)
    o=bpy.context.object;o.rotation_euler=d.to_track_quat('Z','Y').to_euler();o.data.materials.append(mat);return tag(o,key,kind)
def settle(o):
    bpy.context.view_layer.update();z=min((o.matrix_world@Vector(c)).z for c in o.bound_box);o.location.z+=fz-z

# The narrow secondary bedroom needs an actual 1.4 m mattress and compact
# nightstands, rather than pushing the tables into the bed or through a wall.
pa.STYLE['bed_width_m']=1.4
for o in list(bpy.data.objects):
    key=o.get('program_key','')
    if key.endswith('bedroom2_bed'):
        unit=int(key[:3]);loc=o.location.copy();yaw=o.rotation_euler.z;scale=o.scale.copy();bpy.data.objects.remove(o,do_unlink=True)
        fac=ph.SoftBedFactory(48712503+unit);fac.throw_rgb=(.27,.32,.20) if unit==101 else (.43,.27,.32)
        new=fac.spawn_asset(unit);new.location=loc;new.location.y=10.75;new.rotation_euler.z=yaw;new.scale=scale;settle(new);tag(new,key,'furniture')
    elif key.endswith('bedroom2_nightstand'):
        o.location.y=9.78 if o.location.y<10 else 11.72

# Calm stone wet-room finishes instead of randomly selected herringbone wood.
os.environ.update(ROOM_WALL_TILE_ROOMS='bathroom',ROOM_WALL_TILE='.58,.56,.51',ROOM_WALL_TILE_SIZE='.60',
    ROOM_FLOOR_TILE_ROOMS='bathroom',ROOM_FLOOR_TILE='.52,.50,.46',ROOM_TILE_SIZE='.60',
    ROOM_TILE_GROUT='.003',ROOM_TILE_VARY='.035',ROOM_TILE_ROUGH='.48')
import tile_floor,tile_walls
stats={};tile_floor.apply(stats);tile_walls.apply(stats)

shells=[o for o in bpy.data.objects if o.type=='MESH' and o.name.endswith(('.wall','.exterior'))]
for unit,x in [(101,0),(102,21.5)]:
    # Replace native window/blind assembly at the living opening with an actual
    # near-full-height aperture. Original room/sofa placements remain unchanged.
    for o in list(bpy.data.objects):
        if o.type!='MESH' or 'WindowFactory' not in o.name:continue
        pts=[o.matrix_world@Vector(c) for c in o.bound_box];c=sum(pts,Vector())/8
        if abs(c.x-x)<.7 and 6.2<c.y<9.4:bpy.data.objects.remove(o,do_unlink=True)
    loc=(x,7.75,(fz+cz)/2);size=(.75,2.72,cz-fz-.22)
    for wall in shells:
        pts=[wall.matrix_world@Vector(v) for v in wall.bound_box]
        if all(max(v[k] for v in pts)>=loc[k]-size[k]/2 and min(v[k] for v in pts)<=loc[k]+size[k]/2 for k in range(3)):
            remove_box_faces(wall,loc,size)
    box(f'{unit}_living_glass',(x,7.75,(fz+cz)/2),(.015,2.70,cz-fz-.24),glass)
    for y in (6.40,7.75,9.10):box(f'{unit}_living_mullion',(x,y,(fz+cz)/2),(.045,.045,cz-fz-.18),dark)
    for z in (fz+.10,cz-.10):box(f'{unit}_living_glass_rail',(x,7.75,z),(.045,2.74,.045),dark)
    # Soft, genuinely folded mesh curtains; edge panels preserve the glass view.
    xi=.15 if unit==101 else 21.35
    for yc in (6.60,8.90):
        verts=[];faces=[];n=32
        for z in (fz+.035,cz-.16):
            for k in range(n+1):
                y=yc-.20+.40*k/n;xx=xi+.035*math.sin(k*math.pi/2)
                verts.append((xx,y,z))
        for k in range(n):faces.append((k,k+1,n+2+k,n+1+k))
        me=bpy.data.meshes.new('res03_folded_curtain');me.from_pydata(verts,[],faces);me.materials.append(fabric)
        ob=bpy.data.objects.new('curtain',me);bpy.context.scene.collection.objects.link(ob);tag(ob,f'{unit}_curtain')
        rod(f'{unit}_curtain_rod',(xi,yc-.25,cz-.13),(xi,yc+.25,cz-.13),.012,dark)
    # Textured rug and warm practical coves in living and all sleeping rooms.
    mx=3.6 if unit==101 else 17.9
    box(f'{unit}_living_rug',(mx,7.6,fz+.008),(3.3,2.35,.014),cream,'floor_covering')
    for suffix in ('living','master','bedroom2','bedroom3'):
        pts=mapping[f'{unit}_{suffix}']['polygon_m'];xs=[p[0] for p in pts];ys=[p[1] for p in pts]
        x0,x1=min(xs)+.16,max(xs)-.16;y0,y1=min(ys)+.16,max(ys)-.16
        emit=pa._flat('res03_cove_diffuser',(1,.83,.58),.5)
        bs=emit.node_tree.nodes.get('Principled BSDF');bs.inputs['Emission Color'].default_value=(1,.78,.47,1);bs.inputs['Emission Strength'].default_value=2
        for yy in (y0,y1):
            trim=box(f'{unit}_{suffix}_cove_trim',((x0+x1)/2,yy,cz-.045),(x1-x0,.13,.09),white);trim['reference_ceiling_detail']=True
            led=box(f'{unit}_{suffix}_cove_led',((x0+x1)/2,yy,cz-.093),(x1-x0-.04,.035,.006),emit);led['reference_ceiling_detail']=True
        for xx in (x0,x1):
            trim=box(f'{unit}_{suffix}_cove_trim',(xx,(y0+y1)/2,cz-.045),(.13,y1-y0,.09),white);trim['reference_ceiling_detail']=True
    # Actual tabletop decor, never floating above the coffee table.
    table=next(o for o in bpy.data.objects if o.get('program_key')==f'{unit}_living_coffee_table')
    top=max((table.matrix_world@Vector(c)).z for c in table.bound_box)
    box(f'{unit}_coffee_book',(table.location.x+.15,table.location.y,top+.018),(.28,.20,.035),oak)

# Stair treads gain physical stringers, intermediate support columns and
# continuous handrails. The stairwell ceiling is a real void to the next level.
stair_ceiling=bpy.data.objects.get(mapping['stairs']['room_id']+'.ceiling')
if stair_ceiling:stair_ceiling.hide_render=True
for x in (9.45,10.35):rod('lower_stringer',(x,11.55,fz+.015),(x,14.35,fz+1.31),.065,dark,'stair_support')
for x in (11.15,12.05):rod('upper_stringer',(x,14.35,fz+1.31),(x,11.55,fz+2.66),.065,dark,'stair_support')
for x in (9.4,12.1):box('landing_column',(x,15.15,fz+.655),(.12,.12,1.31),dark,'stair_support')
box('landing_cross_beam',(10.75,15.15,fz+1.22),(2.8,.12,.18),dark,'stair_support')
for x in (9.3,10.5,11.0,12.2):
    for k in range(8):
        y0=11.65+(k+.5)*.29;y1=y0+.29
        z0=fz+(k+1)*.15+.92 if x<10.8 else fz+1.35+(9-k)*.15+.92
        z1=z0+(.15 if x<10.8 else -.15)
        rod('stair_continuous_handrail',(x,y0,z0),(x,y1,z1),.025,oak,'stair_guard')
rod('landing_guard',(9.3,15.31,fz+2.27),(12.2,15.31,fz+2.27),.025,oak,'stair_guard')
for x in (9.3,10.0,10.75,11.5,12.2):rod('landing_guard_post',(x,15.31,fz+1.35),(x,15.31,fz+2.27),.015,dark,'stair_guard')
out=base/'scene_candidate_r3.blend';bpy.ops.wm.save_as_mainfile(filepath=str(out))
(base/'correction_r3.json').write_text(json.dumps({'changes':['1.4m secondary beds and real nightstand clearance','stone wet-room surfaces','full-height living glazing with real apertures','folded curtains, rugs, ceiling coves and tabletop books','stair stringers, landing support and continuous handrails','stairwell ceiling opened to next level'],'tile_pass':stats,'visual_acceptance':False},indent=2))
