"""Approved H5 break-room layer, promoted by pkg_g_H5room01_live.

Called by hotel5_shell.apply(); the live wrapper preserves the shared floor World.
Units metres; furniture is local HSSD geometry. This module never opens/saves files.
"""
import math
from pathlib import Path
import bpy
from mathutils import Vector
import hotel5_shell as h
import real_assets as ra
P = 'H5R01_'
F = .131277
ASSETS = Path(__file__).resolve().parents[2] / 'assets/candidates/pkg_g_H5room01'

def mat(name, color, rough=.45, metal=0, emission=0):
    m=bpy.data.materials.new(P+name); m.use_nodes=True
    b=m.node_tree.nodes.get('Principled BSDF'); b.inputs['Base Color'].default_value=(*color,1)
    b.inputs['Roughness'].default_value=rough; b.inputs['Metallic'].default_value=metal
    if emission:
        b.inputs['Emission Color'].default_value=(*color,1); b.inputs['Emission Strength'].default_value=emission
    return m

def textured(name, color, file, scale=1, rough=.3):
    m=mat(name,color,rough); n=m.node_tree.nodes; l=m.node_tree.links; b=n.get('Principled BSDF')
    tc=n.new('ShaderNodeTexCoord'); mp=n.new('ShaderNodeVectorMath');mp.operation='SCALE';mp.inputs[3].default_value=scale
    l.new(tc.outputs['Object'],mp.inputs[0]); t=n.new('ShaderNodeTexImage');t.image=bpy.data.images.load(str(file),check_existing=True);t.projection='BOX';t.projection_blend=.15
    l.new(mp.outputs['Vector'],t.inputs['Vector']); mix=n.new('ShaderNodeMixRGB');mix.blend_type='MULTIPLY';mix.inputs[0].default_value=1;mix.inputs[2].default_value=(*color,1)
    l.new(t.outputs['Color'],mix.inputs[1]);l.new(mix.outputs[0],b.inputs['Base Color'])
    bump=n.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.12;bump.inputs['Distance'].default_value=.00015;l.new(t.outputs['Color'],bump.inputs['Height']);l.new(bump.outputs[0],b.inputs['Normal'])
    return m

def mesh(name, vs, fs, material):
    me=bpy.data.meshes.new(P+name);me.from_pydata(vs,[],fs);me.materials.append(material)
    o=bpy.data.objects.new(P+name,me);bpy.context.collection.objects.link(o);return o

def box(name, loc, size, material, bevel=.008):
    x,y,z=loc;u,v,w=[t/2 for t in size]
    vs=[(x-u,y-v,z-w),(x+u,y-v,z-w),(x+u,y+v,z-w),(x-u,y+v,z-w),(x-u,y-v,z+w),(x+u,y-v,z+w),(x+u,y+v,z+w),(x-u,y+v,z+w)]
    o=mesh(name,vs,[(3,2,1,0),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)],material)
    if bevel:
        b=o.modifiers.new('Machined edges','BEVEL');b.width=min(bevel,min(size)*.25);b.segments=3;o.modifiers.new('Corner normals','WEIGHTED_NORMAL')
    return o

def cyl(name, a,b,r,material, r2=None,verts=48,cap=True):
    a,b=Vector(a),Vector(b);d=b-a;q=d.to_track_quat('Z','Y');r2=r if r2 is None else r2
    vs=[tuple(pt+q@Vector((rr*math.cos(2*math.pi*i/verts),rr*math.sin(2*math.pi*i/verts),0))) for pt,rr in ((a,r),(b,r2)) for i in range(verts)]
    fs=[(i,(i+1)%verts,(i+1)%verts+verts,i+verts) for i in range(verts)]
    if cap:fs += [tuple(reversed(range(verts))),tuple(range(verts,verts*2))]
    o=mesh(name,vs,fs,material)
    for p in o.data.polygons:p.use_smooth=len(p.vertices)==4
    be=o.modifiers.new('Soft rim','BEVEL');be.width=.003;be.segments=3;o.modifiers.new('Normals','WEIGHTED_NORMAL');return o

def bouquet(cx,cy,base,scale=1):
    vs=[];fs=[]
    for k in range(48):
        t=(k+.5)/48;r=.18*math.sqrt(1-t*t);a=k*2.399963
        pos=Vector((cx+r*math.cos(a)*scale,cy+r*math.sin(a)*scale,base+(.14+.19*t)*scale))
        rot=Vector((pos.x-cx,pos.y-cy,.32)).normalized().to_track_quat('Z','Y')
        for ring,count,factor in ((0,6,1),(1,4,.6)):
            for j in range(count):
                az=j*2*math.pi/count+ring*.45+k*.13;along=Vector((math.cos(az),math.sin(az),0));across=Vector((-math.sin(az),math.cos(az),0));first=len(vs);size=.039*scale
                for q in range(6):
                    u=q/5;w=size*.44*math.sin(math.pi*u)**.65+.0002
                    for side in (-1,0,1):
                        v=along*(size*factor*u)+across*(side*w*factor)+Vector((0,0,scale*(.012*ring+.012*math.sin(math.pi*u)-.007*u*u+.003*abs(side))))
                        vs.append(tuple(pos+rot@v))
                for q in range(5):
                    for side in (0,1):a=first+q*3+side;fs.append((a,a+3,a+4,a+1))
        cyl('flower_stem',(cx,cy,base),pos,.0018*scale,M['leaf'],verts=6)
    o=mesh('sculpted_white_bouquet',vs,fs,M['ivory'])
    for p in o.data.polygons:p.use_smooth=True

def flower_head(loc,material):
    # Kept only for the small bud arrangements; the reception uses petal meshes.
    import bmesh
    bm=bmesh.new();bmesh.ops.create_uvsphere(bm,u_segments=12,v_segments=8,radius=.036)
    for v in bm.verts:v.co.z*=.65;v.co+=Vector(loc)
    me=bpy.data.meshes.new(P+'petal');bm.to_mesh(me);bm.free();me.materials.append(material)
    o=bpy.data.objects.new(P+'flower',me);bpy.context.collection.objects.link(o)
    for p in me.polygons:p.use_smooth=True

def carve_south(o):
    """Clip only vertical south faces; robust to inward-facing/open shell normals."""
    import bmesh
    bm=bmesh.new();bm.from_mesh(o.data);bmesh.ops.triangulate(bm,faces=list(bm.faces));bm.to_mesh(o.data);bm.free()
    def clip(poly,axis,bound,greater):
        if not poly:return []
        out=[]
        for a,b in zip(poly,poly[1:]+poly[:1]):
            ia=(a[axis]>=bound-1e-7) if greater else (a[axis]<=bound+1e-7)
            ib=(b[axis]>=bound-1e-7) if greater else (b[axis]<=bound+1e-7)
            if ia:out.append(a)
            if ia!=ib:
                t=(bound-a[axis])/(b[axis]-a[axis]);out.append(a+(b-a)*t)
        return out
    vs=[];fs=[];slots=[];inv=o.matrix_world.inverted()
    for p in o.data.polygons:
        poly=[o.matrix_world@o.data.vertices[i].co for i in p.vertices]
        south=max(v.y for v in poly)-min(v.y for v in poly)<.005 and -.02<sum(v.y for v in poly)/len(poly)<.20 and max(v.z for v in poly)-min(v.z for v in poly)>.02
        pieces=[poly]
        if south:
            left=clip(poly,0,47.975,False);right=clip(poly,0,52.625,True)
            middle=clip(clip(poly,0,47.975,True),0,52.625,False)
            pieces=[left,right,clip(middle,2,.185,False),clip(middle,2,4.435,True)]
        for piece in pieces:
            if len(piece)<3:continue
            first=len(vs);vs.extend(tuple(inv@v) for v in piece);fs.append(tuple(range(first,first+len(piece))));slots.append(p.material_index)
    materials=list(o.data.materials);me=bpy.data.meshes.new(P+'south_aperture_'+o.name);me.from_pydata(vs,[],fs)
    for m in materials:me.materials.append(m)
    for p,slot in zip(me.polygons,slots):p.material_index=slot
    o.data=me

def light(name,loc,energy,color=(1,.78,.51),size=.4,target=None,kind='AREA'):
    d=bpy.data.lights.new(P+name,kind);d.energy=energy;d.color=color
    if kind=='AREA':d.shape='DISK';d.size=size
    elif kind=='POINT':d.shadow_soft_size=size
    o=bpy.data.objects.new(P+name,d);bpy.context.collection.objects.link(o);o.location=loc
    if target:o.rotation_euler=(Vector(target)-o.location).to_track_quat('-Z','Y').to_euler()
    return o

def ring_floor(name,bounds,width,z,material):
    x0,x1,y0,y1=bounds;vs=[(x0,y0,z),(x1,y0,z),(x1,y1,z),(x0,y1,z),(x0+width,y0+width,z),(x1-width,y0+width,z),(x1-width,y1-width,z),(x0+width,y1-width,z)]
    me=bpy.data.meshes.new(P+name);me.from_pydata(vs,[],[(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]);me.materials.append(material);o=bpy.data.objects.new(P+name,me);bpy.context.collection.objects.link(o)

def artwork(y,file,stone,gold,wood):
    x=46.27;z=2.35;w=1.10;hh=1.65
    box('art_back',(x,y,z),(.09,w+.13,hh+.13),wood)
    for dy in (-w/2-.025,w/2+.025):box('art_frame',(x+.06,y+dy,z),(.045,.035,hh+.10),gold,.004)
    for dz in (-hh/2-.025,hh/2+.025):box('art_frame',(x+.06,y,z+dz),(.045,w+.10,.035),gold,.004)
    m=mat('original_canvas',(1,1,1),.83);n=m.node_tree.nodes;t=n.new('ShaderNodeTexImage');t.image=bpy.data.images.load(str(file),check_existing=True);m.node_tree.links.new(t.outputs['Color'],n.get('Principled BSDF').inputs['Base Color'])
    # Explicit UV: right in image is increasing y when seen from the room.
    me=bpy.data.meshes.new(P+'canvas');me.from_pydata([(x+.088,y-w/2,z-hh/2),(x+.088,y+w/2,z-hh/2),(x+.088,y+w/2,z+hh/2),(x+.088,y-w/2,z+hh/2)],[],[(0,1,2,3)]);me.materials.append(m)
    uv=me.uv_layers.new();
    for i,p in enumerate(((0,0),(1,0),(1,1),(0,1))):uv.data[i].uv=p
    o=bpy.data.objects.new(P+'framed_original_art',me);bpy.context.collection.objects.link(o)
    cyl('picture_light',(x+.12,y-.38,z+hh/2+.15),(x+.12,y+.38,z+hh/2+.15),.018,gold)
    light('picture_wash',(x+.36,y,z+hh/2+.12),12,size=.55,target=(x,y,z))

def lantern(x,y,height,gold,stone,glow,glass):
    box('lantern_plinth',(x,y,F+.06),(.43,.43,.12),stone,.02)
    for dx in (-.17,.17):
        for dy in (-.17,.17):box('lantern_upright',(x+dx,y+dy,F+height/2),(.018,.018,height),gold,.003)
    for z in (F+.16,F+height-.04):box('lantern_cap',(x,y,z),(.38,.38,.028),gold,.004)
    cyl('lantern_diffuser',(x,y,F+.19),(x,y,F+.48),.07,glow)
    light('lantern',(x,y,F+.4),9,size=.10,kind='POINT')
    for dy in (-.171,.171):box('lantern_glass',(x,y+dy,F+height*.50),(.30,.002,height-.25),glass,0)

def table(x,y,gold,stone):
    cyl('table_plinth',(x,y,F+.01),(x,y,F+.07),.34,gold)
    cyl('table_drum',(x,y,F+.06),(x,y,F+.46),.39,gold,r2=.41)
    cyl('table_stone',(x,y,F+.46),(x,y,F+.50),.43,stone)
    vase=mat('ceramic',( .89,.86,.75),.22)
    cyl('bud_vase',(x,y,F+.50),(x,y,F+.68),.07,vase,r2=.055)
    # Small clustered flower heads, with stems, genuine geometry.
    import random
    r=random.Random(int(y*100))
    for k in range(17):
        a=k*2.4;rr=.1*math.sqrt(k/17);xx=x+rr*math.cos(a);yy=y+rr*math.sin(a);zz=F+.78+r.uniform(-.04,.04)
        cyl('stem',(x,y,F+.60),(xx,yy,zz),.002,M['leaf'],verts=8)
        flower_head((xx,yy,zz),M['ivory'])

M={}
def apply():
    """Build the approved room layer; the shell wrapper handles repeated calls."""
    sc=bpy.context.scene
    if sc.get('pkg_g_H5room01'):raise RuntimeError('Candidate already applied')
    stone=textured('honed_travertine',( .98,.91,.76),'/bean/ir_pbr_assets/texturecan_staging_v1/assets/texturecan_marble_0008/base_color.jpg',.7,.28)
    dark=textured('nero_marble',( .5,.5,.5),'/bean/ir_pbr_assets/texturecan_staging_v1/assets/texturecan_marble_0007/base_color.jpg',.8,.22)
    gold=mat('brushed_bronze',(.65,.43,.19),.24,1);wood=mat('walnut',(.105,.052,.024),.38);navy=mat('indigo_velvet',(.018,.040,.105),.8)
    bs=navy.node_tree.nodes.get('Principled BSDF');bs.inputs['Sheen Weight'].default_value=.3
    tex=navy.node_tree.nodes.new('ShaderNodeTexNoise');tex.inputs['Scale'].default_value=450;bu=navy.node_tree.nodes.new('ShaderNodeBump');bu.inputs['Distance'].default_value=.00035;bu.inputs['Strength'].default_value=.25;navy.node_tree.links.new(tex.outputs['Fac'],bu.inputs['Height']);navy.node_tree.links.new(bu.outputs[0],bs.inputs['Normal'])
    ivory=mat('linen',(.72,.67,.54),.88);glow=mat('warm_diffuser',(1,.79,.48),.4,emission=3)
    glass=mat('clear_glass',( .94,.97,1),.035);gb=glass.node_tree.nodes.get('Principled BSDF');gb.inputs['Transmission Weight'].default_value=1;gb.inputs['IOR'].default_value=1.45
    mirror=mat('mirror',(.90,.93,.95),.035,1);blue=mat('bluegray_stone',(.10,.16,.22),.24);rug=mat('wool_rug',(.24,.23,.20),.96)
    rn=rug.node_tree.nodes;rt=rn.new('ShaderNodeTexNoise');rt.inputs['Scale'].default_value=650;rb=rn.new('ShaderNodeBump');rb.inputs['Distance'].default_value=.0008;rb.inputs['Strength'].default_value=.3;rug.node_tree.links.new(rt.outputs['Fac'],rb.inputs['Height']);rug.node_tree.links.new(rb.outputs[0],rn.get('Principled BSDF').inputs['Normal'])
    M.update(leaf=mat('stems',(.08,.13,.04),.8),ivory=mat('petals',(.92,.89,.78),.65))
    print('CANDIDATE materials ready',flush=True)
    # Remove only inventoried room furnishings and old applied wall kits.
    doomed=[]
    for o in list(bpy.data.objects):
        if o.type=='MESH':
            lo,hi=h._bb(o);cx=(lo[0]+hi[0])/2;cy=(lo[1]+hi[1])/2
            inside=46.13<cx<54.87 and .13<cy<10.87
            if inside and (o.name.startswith(('Real_','ReceptionDeskFactory','OliveTreeFactory','H5LobbyTravertine','H5R3Lobby','PkgGH5bLobby','H5LobbyInlay'))):doomed.append(o)
        if o.type=='LIGHT' and 46.13<o.location.x<54.87 and .13<o.location.y<10.87:doomed.append(o)
        if o.name.startswith(('H5RingPendant0Cables','H5RingPendant1Cables')):doomed.append(o)
    removed=list(dict.fromkeys(o.name for o in doomed))
    for name in removed:
        o=bpy.data.objects.get(name)
        if o:bpy.data.objects.remove(o,do_unlink=True)
    # Local room height and genuine south opening, private meshes only.
    for name in ('break-room_0/1','break-room_0/1.exterior','break-room_0/1.meshed','break-room_0/1.wall','break-room_0/1.ceiling'):
        o=bpy.data.objects.get(name)
        if not o or o.type!='MESH':continue
        o.data=o.data.copy()
        inv=o.matrix_world.inverted()
        for v in o.data.vertices:
            w=o.matrix_world@v.co
            if w.z>3.5:w.z+=.995573;v.co=inv@w
        if name in ('break-room_0/1.wall','break-room_0/1.exterior','break-room_0/1.meshed','break-room_0/1') and len(o.data.polygons):
            carve_south(o)
    # Rich floor + actual separate stone and bronze inlays, no coplanar overlaps.
    floor=bpy.data.objects.get('break-room_0/1.floor');floor.data=floor.data.copy();floor.data.materials.clear();floor.data.materials.append(stone)
    ring_floor('marble_band',(47.1,53.9,1.0,9.7),.22,F+.002,blue)
    ring_floor('bronze_outer',(47.075,53.925,.975,9.725),.018,F+.003,gold)
    ring_floor('bronze_inner',(47.33,53.67,1.23,9.47),.018,F+.003,gold)
    print('CANDIDATE architecture ready',flush=True)
    # West wall relief, avoiding both existing door spans.
    for ya,yb in ((.16,3.04),(4.62,8.47),(10.18,10.83)):
        box('west_stone',(46.22,(ya+yb)/2,2.23),(.14,yb-ya,4.20),stone)
        box('west_dado',(46.32,(ya+yb)/2,.40),(.12,yb-ya,.50),stone)
        for y in (ya+.07,yb-.07):
            box('west_pilaster',(46.35,y,2.23),(.27,.14,4.20),stone)
            box('west_gold_reveal',(46.493,y,2.23),(.008,.018,4.10),gold,.001)
    artwork(1.65,ASSETS/'art_01.png',stone,gold,wood);artwork(6.28,ASSETS/'art_02.png',stone,gold,wood)
    box('west_mirror',(46.31,7.67,2.30),(.016,.58,3.4),mirror,.002)
    # Deep east bays: dark recess, mirror, two separate lattice planes and stone piers.
    spans=((1.05,2.18),(2.18,3.31),(3.31,4.63),(6.37,7.57),(7.57,8.77),(8.77,10.08))
    for i,(a,b) in enumerate(spans):
        mid=(a+b)/2;box('bay_back',(54.82,mid,2.23),(.05,b-a-.02,4.20),wood)
        box('bay_mirror',(54.775,mid,2.23),(.018,b-a-.13,3.96),mirror,.001)
        for y in (a+.04,b-.04):box('stone_pier',(54.67,y,2.23),(.30,.105,4.20),stone)
        for x,step,thick in ((54.71,.35,.016),(54.55,.67,.022)):
            for j in range(1,int((b-a)/step)+1):
                y=a+j*step
                if y<b-.08:box('screen_vertical',(x,y,2.26),(.028,thick,3.9),gold,.003)
            for z in ( .40,1.05,1.70,2.35,3.0,3.65,4.22):box('screen_cross',(x,mid,z),(.028,b-a-.16,thick),gold,.003)
        if i in (0,3,5):
            box('sconce_back',(54.46,mid,2.65),(.06,.15,.80),gold)
            box('sconce_diffuser',(54.40,mid,2.65),(.055,.07,.65),glow)
            light('wall_wash',(54.25,mid,2.65),16,size=.22,kind='POINT')
    print('CANDIDATE wall bays ready',flush=True)
    # North wall: articulated stone relief replaces the inherited flat timber field.
    for a,b in ((46.27,49.62),(51.20,54.75)):
        mid=(a+b)/2
        box('north_stone',(mid,10.77,2.23),(b-a,.15,4.20),stone)
        box('north_dado',(mid,10.63,.40),(b-a,.15,.50),stone)
        for x in (a+.08,mid,b-.08):
            box('north_pilaster',(x,10.60,2.23),(.14,.27,4.20),stone)
            box('north_pilaster_reveal',(x,10.455,2.23),(.018,.008,4.10),gold,.001)
        for x in ((a+mid)/2,(mid+b)/2):
            box('north_mirror',(x,10.67,2.40),(.62,.018,2.95),mirror,.002)
            for dx in (-.33,.33):box('north_frame',(x+dx,10.63,2.40),(.018,.03,3.0),gold,.002)
        box('north_cornice',(mid,10.59,4.30),(b-a,.33,.12),stone)
    # A thin layered cornice over, rather than across, the preserved north doorway.
    box('north_door_lintel',(50.41,10.69,3.40),(1.50,.18,1.80),stone)
    # Coordinated real armchairs, two coherent clusters. Clear central cross route.
    chairs=[]
    for k,y in enumerate((3.0,7.5)):
        o=cyl('oval_wool_rug',(49.4,y,F+.004),(49.4,y,F+.014),1.75,rug,verts=96)
        table(49.4,y,gold,stone)
        for j,a in enumerate((0,math.pi/2,math.pi,3*math.pi/2)):
            x=49.4+1.20*math.cos(a);yy=y+1.20*math.sin(a)
            o=ra.hssd('25d1b247c63eceb6ba2dfc4e296209a8cf06816a',100+k*4+j,x,yy,F+.018,a+math.pi,fit=(.92,1.02,.92),grow=True)
            if o is None:raise RuntimeError('Required Reginald chair unavailable; no primitive substitute')
            o.name=P+f'Reginald_{k}_{j}';o.data=o.data.copy()
            for mi,m in enumerate(o.data.materials):o.data.materials[mi]=gold if m and m.name.endswith('::002') else navy
            chairs.append(o.name)
            # Soft loose cushions on the existing upholstered seat.
            forward=Vector((math.cos(a+math.pi),math.sin(a+math.pi),0))
            pp=Vector((x,yy,F+.62))-forward*.20
            ra.soft(P+'loose_linen_cushion',ivory,pp.x,pp.y,pp.z,.36,.14,.31,yaw=a+math.pi/2,seed=100+j)
    print('CANDIDATE chairs ready',flush=True)
    # Reception, a properly layered stone/bronze counter with open staff side.
    box('desk_toe',(53.10,2.75,F+.075),(.70,3.18,.15),wood,.025)
    box('desk_front',(52.72,2.75,F+.59),(.16,3.4,.98),stone,.018)
    for y in (1.10,4.40):box('desk_end',(53.10,y,F+.58),(.90,.10,1.0),dark,.015)
    box('desk_top',(53.10,2.75,F+1.10),(.98,3.50,.065),dark,.022)
    for z in (F+.17,F+1.04):box('desk_bronze_trim',(52.625,2.75,z),(.018,3.38,.024),gold,.003)
    for y in (1.2,4.3):box('desk_corner_trim',(52.625,y,F+.60),(.018,.022,.88),gold,.003)
    for y in (1.55,3.95):
        cyl('lamp_foot',(53.0,y,F+1.14),(53.0,y,F+1.18),.13,gold)
        cyl('lamp_stem',(53.0,y,F+1.18),(53.0,y,F+1.59),.018,gold)
        cyl('linen_lampshade',(53.0,y,F+1.45),(53.0,y,F+1.76),.21,ivory,r2=.15,cap=False)
        light('desk_lamp',(53.0,y,F+1.52),13,size=.12,kind='POINT')
    flower_base=F+1.14
    cyl('reception_ceramic_vase',(53.05,2.75,flower_base),(53.05,2.75,flower_base+.27),.105,ivory,r2=.082)
    bouquet(53.05,2.75,flower_base+.08,1.50)
    # Floor lanterns/display frames; kept outside the cross route and staff aisle.
    for x,y,ht in ((46.76,2.55,1.3),(46.76,6.35,1.55),(54.14,7.15,1.4),(54.14,9.90,1.65)):lantern(x,y,ht,gold,stone,glow,glass)
    # South glazing has depth, real glass, reveals and mullions. No picture panel.
    box('window_glass',(50.30,.11,2.28),(4.56,.012,4.10),glass,0)
    for x in (48.0,49.15,50.30,51.45,52.60):box('window_mullion',(x,.21,2.28),(.035,.13,4.20),gold,.003)
    for z in (.19,4.36):box('window_transom',(50.3,.21,z),(4.67,.13,.045),gold,.003)
    box('window_stone_sill',(50.3,.30,.22),(4.72,.40,.12),stone,.015)
    # Raised perimeter coffers, split rails avoid overlapping faces.
    ceilingmat=mat('ceiling_plaster',(.72,.69,.61),.90)
    ceil=bpy.data.objects.get('break-room_0/1.ceiling');ceil.data.materials.clear();ceil.data.materials.append(ceilingmat)
    for xa,xb in ((46.25,47.55),(53.35,54.75)):
        for x in (xa,xb):box('coffer_long_rail',(x,5.5,4.42),(.12,10.45,.24),wood)
        for i in range(14):
            y=.33+i*.79
            box('coffer_cross',( (xa+xb)/2,y,4.42),(xb-xa-.12,.10,.24),wood)
            box('coffer_gold',( (xa+xb)/2,y-.057,4.315),(xb-xa-.14,.012,.018),gold,.002)
            if i%2==0:
                cyl('recessed_downlight',((xa+xb)/2,y+.30,4.55),((xa+xb)/2,y+.30,4.57),.065,gold)
                light('coffer_down',((xa+xb)/2,y+.30,4.49),17,size=.14,target=((xa+xb)/2,y+.30,F))
        light('coffer_bounce',((xa+xb)/2,5.5,4.30),45,size=3,target=((xa+xb)/2,5.5,4.65))
    for y in (.30,10.65):
        box('ceiling_return',(50.45,y,4.42),(6.65,.16,.24),wood)
        box('ceiling_gold_return',(50.45,y-.09,4.315),(6.65,.012,.018),gold,.002)
    for x in (47.77,53.13):
        box('tray_step',(x,5.50,4.57),(.15,10.02,.12),ceilingmat,.014)
        box('tray_gold',(x,5.50,4.50),(.012,9.97,.012),gold,.002)
    for y in (.57,10.43):
        box('tray_step',(50.45,y,4.57),(5.21,.15,.12),ceilingmat,.014)
        box('tray_gold',(50.45,y,4.50),(5.20,.012,.012),gold,.002)
    for k,y in enumerate((3.0,7.5)):
        o=bpy.data.objects.get('H5RingPendant'+str(k))
        if o:
            oldcenter=Vector(((h._bb(o)[0][0]+h._bb(o)[1][0])/2,(h._bb(o)[0][1]+h._bb(o)[1][1])/2,0))
            o.data=o.data.copy()
            for v in o.data.vertices:
                w=o.matrix_world@v.co;w.x=49.4+(w.x-oldcenter.x)*1.2;w.y=y+(w.y-oldcenter.y)*1.2;w.z+=.55;v.co=o.matrix_world.inverted()@w
            for idx,m in enumerate(o.data.materials):
                if m and ('led' not in m.name.lower() and 'emit' not in m.name.lower()):o.data.materials[idx]=gold
        for dx in (-.30,.30):cyl('pendant_cable',(49.4+dx,y,3.54),(49.4+dx,y,4.58),.0035,wood,verts=8)
        light('ring_soft',(49.4,y,3.40),45,size=.8,target=(49.4,y,F))
    # Preview uses its own sky; the live shell wrapper restores the shared floor World.
    card=bpy.data.objects.get('EnvWindowCard_1')
    if card:card.hide_render=True
    sc.world=sc.world.copy();sc.world.name=P+'daylight_world';sc.world.use_nodes=True;n=sc.world.node_tree.nodes;n.clear();out=n.new('ShaderNodeOutputWorld');bg=n.new('ShaderNodeBackground');bg.inputs[1].default_value=.12;sky=n.new('ShaderNodeTexSky');sky.sky_type='NISHITA';sky.sun_elevation=math.radians(12);sky.sun_rotation=-math.pi/2;sc.world.node_tree.links.new(sky.outputs[0],bg.inputs[0]);sc.world.node_tree.links.new(bg.outputs[0],out.inputs[0])
    sea=mat('sea_water',(.025,.11,.16),.13,.1);b=sea.node_tree.nodes.get('Principled BSDF');b.inputs['IOR'].default_value=1.333
    no=sea.node_tree.nodes.new('ShaderNodeTexNoise');no.inputs['Scale'].default_value=2.2;tc=sea.node_tree.nodes.new('ShaderNodeTexCoord');sea.node_tree.links.new(tc.outputs['Object'],no.inputs['Vector']);bu=sea.node_tree.nodes.new('ShaderNodeBump');bu.inputs['Distance'].default_value=.13;bu.inputs['Strength'].default_value=.30;sea.node_tree.links.new(no.outputs['Fac'],bu.inputs['Height']);sea.node_tree.links.new(bu.outputs[0],b.inputs['Normal'])
    box('real_sea',(50,-650,-18),(1800,1300,.10),sea,0)
    terrainmat=mat('distant_headlands',(.10,.16,.14),.95)
    for k,(cx,cy,rx,ry,ht) in enumerate(((-70,-440,165,180,38),(240,-650,200,250,42))):
        vs=[];fs=[];N=45
        for i in range(N):
            for j in range(N):
                x=-1+2*i/(N-1);y=-1+2*j/(N-1);rad=max(0,1-x*x-y*y);z=-19+ht*rad**1.6*(.86+.10*math.sin(x*19+y*11)+.04*math.sin(y*43));vs.append((cx+x*rx,cy+y*ry,z))
        for i in range(N-1):
            for j in range(N-1):a=i*N+j;fs.append((a,a+1,a+N+1,a+N))
        me=bpy.data.meshes.new(P+'terrain');me.from_pydata(vs,[],fs);me.materials.append(terrainmat);o=bpy.data.objects.new(P+'headland'+str(k),me);bpy.context.collection.objects.link(o)
        for p in me.polygons:p.use_smooth=True
    wl=light('window_daylight',(50.3,-.25,2.5),170,color=(.73,.86,1),size=3.8,target=(50.3,5.5,1.1))
    wl.visible_camera=False;wl.visible_glossy=False;wl.visible_transmission=False
    sc['pkg_g_H5room01']=True;bpy.context.view_layer.update()
    return {'removed':removed,'chairs':chairs,'live_integration':False,'ceiling_m':4.65,'tag':'pkg_g_H5room01'}
