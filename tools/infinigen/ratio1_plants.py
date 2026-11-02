"""pkg_c real entrance shrubs and S39 foliage. Hook: RATIO1_PLANTS=1.
Call apply(stats) after the scene shell. No source scene is saved here.
"""
from __future__ import annotations
import os
import bpy
from mathutils import Vector
import ratio1_common as rc
import real_assets as ra

PREFIX = 'PkgCPlant_'

def _tag(o, name):
    if o is None:
        raise RuntimeError('pkg_c required plant asset unavailable: '+name)
    o.name=PREFIX+name
    o['pkg_c_source']='HSSD real mesh'
    # Isolate materials before adjusting imported foliage shared with other assets.
    o.data=o.data.copy()
    for i,m in enumerate(o.data.materials):
        if m is not None:o.data.materials[i]=m.copy()
    rc.plant_fix(o)
    return o

def _green(o):
    """Keep texture detail; clamp pale foliage to a leafy green multiply.
    Only leaf material slots, never pot, soil, or bark materials.
    """
    for m in o.data.materials:
        if not m or not m.use_nodes:continue
        name=m.name.lower()
        leaf=any(w in name for w in ('leaf','leav','foliage','plant','green'))
        # HSSD anonymizes slot names; identify leafy albedo by sampled chroma.
        if not leaf:
            for node in m.node_tree.nodes:
                if node.type=='TEX_IMAGE' and node.image and node.image.size[0]:
                    import numpy as np
                    rgba=np.asarray(node.image.pixels[:],dtype=float).reshape(-1,4)[::64]
                    rgb=rgba[:,:3].mean(axis=0)
                    leaf=bool(rgb[1]>rgb[0]*1.08 and rgb[1]>rgb[2]*1.10)
                    if leaf:break
        if not leaf:continue
        b=next((n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
        if not b:continue
        nt=m.node_tree
        if b.inputs['Base Color'].is_linked:
            src=b.inputs['Base Color'].links[0].from_socket
            mix=nt.nodes.new('ShaderNodeMixRGB');mix.blend_type='MULTIPLY';mix.inputs[0].default_value=1
            mix.inputs[2].default_value=(0.55,0.80,0.45,1)
            nt.links.new(src,mix.inputs[1]);nt.links.new(mix.outputs[0],b.inputs['Base Color'])
        else:b.inputs['Base Color'].default_value=(0.035,0.15,0.018,1)
        for key in ('Metallic','Roughness'):
            for l in list(b.inputs[key].links):nt.links.remove(l)
        b.inputs['Metallic'].default_value=0;b.inputs['Roughness'].default_value=.62
        if 'Emission Strength' in b.inputs:
            for l in list(b.inputs['Emission Strength'].links):nt.links.remove(l)
            b.inputs['Emission Strength'].default_value=0

def apply(stats=None, tag=None):
    stats={} if stats is None else stats
    if os.environ.get('RATIO1_PLANTS')!='1':return stats
    if bpy.context.scene.get('pkg_c_plants_v1'):return stats
    floor=next((bpy.data.objects.get(n) for n in ('break-room_0/0.floor','convenience.floor','cafe.floor','cafe_0/0.floor') if bpy.data.objects.get(n) is not None),None)
    if floor is None:return stats
    lo,hi=rc.bb(floor)
    if tag is None:
        tag='S39' if bpy.context.scene.get('ir_brick_shell') or any(o.name.startswith('BrickDome') for o in bpy.data.objects) else ('S38' if any(o.name.startswith('Liq') for o in bpy.data.objects) else 'S37')
    made=[]
    if tag=='S37':
        # Follow the existing entry mat rather than assuming the entry is centered.
        mat=next((o for o in bpy.data.objects if 'EntranceMat' in o.name),None)
        a,b=rc.bb(mat) if mat else (lo,hi)
        cx=(a[0]+b[0])/2 if mat else lo[0]+2
        cy=(a[1]+b[1])/2 if mat else lo[1]+.9
        for i,x in enumerate((max(lo[0]+.6,cx-1.05),min(hi[0]-.6,cx+1.05))):
            pot=_tag(ra.hssd('HSSD_23b529869de811e2fd7fae49797e0f3be4b3edad',0,x,cy,lo[2],0,fit=(.5,.5,.65),grow=True),'S37Pot%d'%i)
            shrub=_tag(ra.hssd('HSSD_db2f10d91d5a3a26ce56a6f9eb178c66ebc989a8',0,x,cy,lo[2]+.45,0,fit=(.82,.82,1.3),grow=True),'S37Shrub%d'%i)
            _green(shrub);made.extend([pot.name,shrub.name])
    elif tag=='S39':
        # Preserve existing plant locations and replace pale material response.
        import json,re
        index=json.load(open('/jarvis/project/robomituba/vendor_datasets/hssd_objects/hssd_object_index.json'))['objects']
        plant_ids={e['id'] for e in index if e.get('hssd_category')=='plant'}
        for o in list(bpy.data.objects):
            if o.type!='MESH' or not o.name.startswith(('Real_hssd','HssdPlant')):continue
            source_id=re.search(r'HSSD_[0-9a-f]+',o.name)
            if not o.name.startswith('HssdPlant') and (not source_id or source_id.group() not in plant_ids):continue
            a,b=rc.bb(o)
            if b[2]-a[2]<.65 or 'christmas' in ' '.join(m.name.lower() for m in o.data.materials if m):continue
            # plant_fix is shared, but material copies keep changes local.
            o.data=o.data.copy()
            for i,m in enumerate(o.data.materials):
                if m:o.data.materials[i]=m.copy()
            rc.plant_fix(o);_green(o);made.append(o.name)
        # Real, dense specimen at the sofa/window end; avoid the tree corner.
        x,y=hi[0]-.8,lo[1]+.9
        shrub=_tag(ra.hssd('HSSD_db2f10d91d5a3a26ce56a6f9eb178c66ebc989a8',0,x,y,lo[2],0,fit=(.85,.85,1.5),grow=True),'S39Shrub')
        _green(shrub);made.append(shrub.name)
    bpy.context.scene['pkg_c_plants_v1']=True
    stats['pkg_c_plants']={'tag':tag,'objects':made}
    return stats
