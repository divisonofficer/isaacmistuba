"""Catalog-asset apartment hall dressing; opt in with APT_CORRIDOR=1.

Existing tagged hall assets are retained. New furniture uses free strips and
wall_face measurements, leaving the central circulation path unobstructed.
"""
import os
import math
import collections
import bpy


def _visible_rack(a, room, lo, hi):
    """Keep one entry rack visible in the supplied hallway views, on free floor."""
    import json
    from mathutils import Vector
    path=bpy.data.filepath.lower()
    tag=next((t for t in ('p7','p8','p9') if t in path),None)
    if tag!='p8':return None
    apt,stem={'p7':('APT5','apt5'),'p8':('APT6','apt6'),'p9':('APT7','apt7')}[tag]
    pose_path='/jarvis/project/robomituba/data/venue_refs/floor_plans_v3/'+apt+'/'+stem+'_hall_views.json'
    poses=[p for p in json.load(open(pose_path)) if p['name'].startswith(room.replace('/','-')+'_')]
    if not poses:return None
    racks=[o for o in bpy.data.objects if o.get('apt_corridor_room')==room and o.get('apt_corridor_category')=='shoe_rack']
    if not racks:return None
    def visible(point, allowed=None, distance_score=False):
        closest=float('inf')
        dg=bpy.context.evaluated_depsgraph_get()
        for pose in poses:
            origin=Vector(pose['location']);delta=point-origin
            forward=(Vector(pose['target'])-origin).normalized()
            if forward.angle(delta)>math.radians(pose.get('hfov',75)/2-7):continue
            hit,loc,normal,face,obj,matrix=bpy.context.scene.ray_cast(dg,origin,delta.normalized(),distance=max(.01,delta.length-.03))
            if not hit or obj==allowed:closest=min(closest,delta.length)
        return closest if distance_score else math.isfinite(closest)
    for obj in racks:
        aa,bb=a._bb(obj)
        if visible(Vector(((aa[0]+bb[0])/2,(aa[1]+bb[1])/2,(aa[2]+bb[2])/2)),obj):return None
    obj=racks[0];original=obj.matrix_world.copy()
    obj.location+=Vector((1000,1000,1000));bpy.context.view_layer.update()
    obs=a._obs_all(lo,hi)
    best=None;best_score=float('inf')
    for attempt in range(60):
        strip=a._strip(room,lo,hi,obs,.85,.34,prefer='S')
        if strip is None:break
        point=Vector((strip[0],strip[1],lo[2]+.23))
        score=visible(point,distance_score=True)
        if score<best_score:best,best_score=strip,score
        obs.append(strip[4])
    if best is not None:
        a._ra()._stand(obj,best[0],best[1],lo[2],best[2]-math.atan2(a._ra().ABO_FRONT[1],a._ra().ABO_FRONT[0]),(.85,.34,.5))
        bpy.context.view_layer.update()
        obj['apt_corridor_visibility_relocated']=True
        return {'object':obj.name,'centre_xy':[best[0],best[1]],'wall':best[3],'visible_camera_distance_m':best_score}
    obj.matrix_world=original;bpy.context.view_layer.update()
    return None


def apply(stats=None):
    stats = stats if stats is not None else {}
    if os.environ.get('APT_CORRIDOR','0') != '1':
        return stats
    import apt_shell as a
    import wall_face
    ra=a._ra()
    report={}
    for room,(lo,hi,kind) in a._rooms().items():
        if kind!='hallway':
            continue
        inner_lo,inner_hi=wall_face.inner_box(room)
        if inner_lo is None:
            continue
        def inside(o):
            if o.type!='MESH':return False
            p,q=a._bb(o)
            return lo[0]<(p[0]+q[0])/2<hi[0] and lo[1]<(p[1]+q[1])/2<hi[1]
        counts=collections.Counter()
        def tag(o,category):
            if o is None:return
            o.name=f'apt_Corridor_{category}({room}|{counts[category]})'
            o['apt_corridor_room']=room;o['apt_corridor_category']=category
            # Imported everyday objects must not illuminate the room.
            if category not in ('sconce','exit_sign'):
                for slot in o.material_slots:
                    m=slot.material
                    if m and m.node_tree:
                        for node in m.node_tree.nodes:
                            if node.type=='BSDF_PRINCIPLED' and 'Emission Strength' in node.inputs:
                                if node.inputs['Emission Strength'].is_linked:
                                    for link in list(node.inputs['Emission Strength'].links):m.node_tree.links.remove(link)
                                node.inputs['Emission Strength'].default_value=0
            counts[category]+=1
        mapping={'console':'console','floorplant':'plant','art':'print','sconce':'sconce','shoerack':'shoe_rack','exitsign':'exit_sign','extinguisher':'extinguisher','doormat':'mat','hallrunner':'runner','bench':'bench'}
        for o in list(bpy.data.objects):
            if inside(o):
                if o.get('apt_corridor_room')==room:
                    counts[o['apt_corridor_category']]+=1
                elif o.get('r2') in mapping:
                    tag(o,mapping[o['r2']])
                elif any(key in o.name for key in ('WallArtFactory','PictureFrameFactory')):
                    tag(o,'print')
        bpy.context.view_layer.update()
        obs=a._obs_all(lo,hi)
        # Physical furniture: use free measured wall strips, never guessed centres.
        specifications=[('console',1.1,.38,.88,lambda x,y,z,yaw:ra.abo('console',902,x,y,z,yaw,fit=(1.1,.38,.88))),
                        ('shoe_rack',.8,.34,.5,lambda x,y,z,yaw:ra.hssd('Cedar Shoe Rack|Sko Shoe Rack',903,x,y,z,yaw,fit=(.8,.34,.5))),
                        ('plant',.45,.45,1.3,lambda x,y,z,yaw:ra.hssd(a.R2_FLOORPLANT,904,x,y,z,yaw,fit=(.45,.45,1.3)))]
        for cat,length,depth,height,spawn in specifications:
            if counts[cat]:continue
            sp=a._strip(room,lo,hi,obs,length,depth,prefer='E')
            if sp is None:continue
            o=spawn(sp[0],sp[1],lo[2],sp[2]);tag(o,cat)
            if o:obs.append(sp[4])
        # Every actual entry gets a scanned mat and a real engraved slate plaque.
        doors=[]
        for o in bpy.data.objects:
            if o.type=='MESH' and o.name.startswith('DoorCasingFactory'):
                p,q=a._bb(o);x,y=(p[0]+q[0])/2,(p[1]+q[1])/2
                if lo[0]-.3<x<hi[0]+.3 and lo[1]-.3<y<hi[1]+.3:
                    doors.append((o,x,y,p,q))
        for index,(door,x,y,p,q) in enumerate(doors):
            entry=door.name
            if any(o.get('apt_corridor_entry')==entry for o in bpy.data.objects):continue
            side=a._side_of(lo,hi,x,y);along=x if side in 'SN' else y
            wid=q[0]-p[0] if side in 'SN' else q[1]-p[1]
            px,py,yaw=a._wall_pt(room,lo,hi,side,along+wid/2+.18,.025)
            plate=a._picture('Engraved Slate House Number',910+index,px,py,lo[2]+1.48,yaw,.14,.12)
            tag(plate,'number_plate')
            if plate:
                plate['apt_corridor_entry']=entry
                for legacy in bpy.data.objects:
                    if legacy.get('r2')!='plate' or legacy.type!='MESH':continue
                    aa,bb=a._bb(legacy)
                    if math.hypot((aa[0]+bb[0])/2-px,(aa[1]+bb[1])/2-py)<.2:
                        legacy.hide_render=True;legacy.hide_viewport=True
            px,py,yaw=a._wall_pt(room,lo,hi,side,along,.38)
            # Do not duplicate mats already within 60 cm of this entry.
            near=False
            for m in bpy.data.objects:
                if m.get('apt_corridor_category') not in ('mat','runner'):continue
                aa,bb=a._bb(m)
                if math.hypot((aa[0]+bb[0])/2-px,(aa[1]+bb[1])/2-py)<.6:near=True
            if not near:
                o=ra.hssd('door.?mat|coir mat|welcome mat',930+index,px,py,lo[2]+.002,yaw,fit=(.75,.45,.025));tag(o,'mat')
        # Upper-wall assets may occupy the wall above floor furniture but not doors.
        wall_obs=[]
        for door,x,y,p,q in doors:wall_obs.append((p[0]-.12,q[0]+.12,p[1]-.12,q[1]+.12))
        # Existing frames, windows, curtains, plates and tall cabinets already
        # occupy upper-wall spans, even when they have no shell dressing tag.
        for obj in bpy.data.objects:
            if obj.type!='MESH' or obj.name.endswith(a.SKIP_OBJ):continue
            aa,bb=a._bb(obj)
            if bb[2]<=lo[2]+1.0 or aa[2]>=lo[2]+2.5:continue
            if not (bb[0]>lo[0] and aa[0]<hi[0] and bb[1]>lo[1] and aa[1]<hi[1]):continue
            if max(bb[0]-aa[0],bb[1]-aa[1])>6:continue
            wall_obs.append((aa[0]-.08,bb[0]+.08,aa[1]-.08,bb[1]+.08))
        for cat,number,length,height,rx in [('print',3,.65,1.35,a.R2_ART),('sconce',2,.25,1.85,'IC C/W1 Sconce'),('exit_sign',1,.48,2.15,'exit sign'),('extinguisher',1,.25,.3,'Korean Fire Extinguisher 01')]:
            for k in range(max(0,number-counts[cat])):
                sp=a._strip(room,lo,hi,wall_obs+(obs if cat=='extinguisher' else []),length,.14,prefer='N' if k%2 else 'S')
                if sp is None:break
                along=sp[0] if sp[3] in 'SN' else sp[1]
                x,y,yaw=a._wall_pt(room,lo,hi,sp[3],along,.06)
                if cat in ('print','exit_sign'):
                    o=a._picture(rx,950+k,x,y,lo[2]+height,yaw,length,.65 if cat=='print' else .25)
                else:
                    o=ra.hssd(rx,970+k,x,y,lo[2]+height,yaw,fit=(length,.22,.3 if cat=='sconce' else .5))
                tag(o,cat)
                if o:wall_obs.append(sp[4])
        report[room]=dict(counts)
    moves=[]
    for room,(lo,hi,kind) in a._rooms().items():
        if kind=='hallway':
            move=_visible_rack(a,room,lo,hi)
            if move:moves.append(move)
    stats['apt_corridor_visible_rack_moves']=moves
    stats['apt_corridor']=report
    return stats
