"""pkg_c visible real checkout packs/cup towers and S38 end gifts.
Hook: RATIO1_CHECKOUT=1. Call apply(stats) after the scene shell.
"""
from __future__ import annotations
import os,math
import bpy
import ratio1_common as rc
import real_assets as ra

def _fit(o,name,center,z,fit,yaw=0):
    if o is None:raise RuntimeError('pkg_c required real prop unavailable: '+name)
    bpy.context.view_layer.update()
    a,b=rc.bb(o);dims=[b[i]-a[i] for i in range(3)]
    k=min(fit[i]/max(dims[i],1e-5) for i in range(3))
    o.scale=tuple(v*k for v in o.scale);bpy.context.view_layer.update();a,b=rc.bb(o)
    o.location.x+=center[0]-(a[0]+b[0])/2;o.location.y+=center[1]-(a[1]+b[1])/2;o.location.z+=z-a[2]
    o.name='PkgCProp_'+name;o['pkg_c_kind']='pack' if name.startswith('Pack') else 'cup' if name.startswith('Cup') else 'gift'
    return o

def apply(stats=None,tag=None):
    stats={} if stats is None else stats
    if os.environ.get('RATIO1_CHECKOUT')!='1' or bpy.context.scene.get('pkg_c_checkout_v1'):return stats
    if not any(bpy.data.objects.get(n) is not None for n in ('break-room_0/0.floor','convenience.floor')):return stats
    if tag=='S39' or bpy.context.scene.get('ir_brick_shell'):return stats
    if tag is None:tag='S38' if any(o.name.startswith('Liq') for o in bpy.data.objects) else 'S37'
    made=[]
    if tag=='S37':
        cs=[o for o in bpy.data.objects if o.type=='MESH' and o.name.startswith('CheckoutCounterFactory')]
        if not cs:raise RuntimeError('pkg_c no checkout counter found')
        counter=sorted(cs,key=lambda o:rc.bb(o)[0][0])[0];a,b=rc.bb(counter)
        # Counter shells can include front shelf stock and tall POS attachments.
        zs=[(counter.matrix_world@v.co).z for v in counter.data.vertices]
        z=max(v for v in zs if v<a[2]+1.15)+.006
        along_x=(b[0]-a[0])>=(b[1]-a[1]);cx,cy=(a[0]+b[0])/2,(a[1]+b[1])/2
        length=(b[0]-a[0]) if along_x else (b[1]-a[1]);step=min(.19,(length-.5)/7)
        for j in range(16):
            u=(j%8-3.5)*step;v=(-.12 if j<8 else .12)
            xy=(cx+u,cy+v) if along_x else (cx+v,cy+u)
            o=ra.lib('FoodBagFactory' if j%2 else 'FoodBoxFactory',730+j,*xy,z,yaw=math.pi/2 if not along_x else 0)
            o=_fit(o,'Pack%02d'%j,xy,z,(.14,.11,.20));made.append(o.name)
        for t in range(2):
            u=(.5-t)*(length-.3)
            xy=(cx+u,cy) if along_x else (cx,cy+u)
            for j in range(8):
                o=ra.hssd('HSSD_b09008488fdb3dc94b0be198e64f8577a32af1c6',0,*xy,z+j*.028,0,fit=(.10,.10,.14),grow=True)
                o=_fit(o,'Cup%d_%d'%(t,j),xy,z+j*.028,(.10,.10,.14));made.append(o.name)
    else:
        gs=[o for o in bpy.data.objects if o.type=='MESH' and o.name.startswith('GondolaFactory')]
        rx='christmas box present (red-blue|black-gold|white-gold|white-blue)'
        for gi,g in enumerate(sorted(gs,key=lambda o:o.name)):
            a,b=rc.bb(g);ay=b[1]-a[1]>b[0]-a[0]
            for end in range(2):
                for j in range(3):
                    x=a[0]+.16+j*.23 if ay else (a[0]+.18 if end==0 else b[0]-.18)
                    y=(a[1]+.18 if end==0 else b[1]-.18) if ay else a[1]+.16+j*.23
                    o=ra.hssd(rx,820+gi*6+end*3+j,x,y,b[2]+.005,0,fit=(.20,.18,.30),grow=True)
                    if o is None:raise RuntimeError('pkg_c gift pool unavailable')
                    o.name='PkgCProp_Gift%d_%d_%d'%(gi,end,j);o['pkg_c_kind']='gift';made.append(o.name)
    bpy.context.scene['pkg_c_checkout_v1']=True
    stats['pkg_c_checkout']={'tag':tag,'objects':made}
    return stats
