"""Metre-scale PBR detail for reference scenes; no lighting baked into albedo.

Layered normals carry fine relief; actual edge bevels carry silhouette highlights.
Dielectrics remain metallic0; bare metal uses metallic1 with brushed roughness.
"""
from pathlib import Path
import bpy


def material(name,color,roughness,metallic=0):
    m=bpy.data.materials.new(name);m.use_nodes=True;n=m.node_tree.nodes;l=m.node_tree.links;n.clear()
    out=n.new('ShaderNodeOutputMaterial');bs=n.new('ShaderNodeBsdfPrincipled');l.new(bs.outputs['BSDF'],out.inputs['Surface'])
    bs.inputs['Base Color'].default_value=(*color,1);bs.inputs['Roughness'].default_value=roughness;bs.inputs['Metallic'].default_value=metallic
    tc=n.new('ShaderNodeTexCoord');geo=n.new('ShaderNodeNewGeometry')
    return m,n,l,bs,tc,geo


def noise(n,l,vector,scale,stretch=None):
    if stretch:
        mp=n.new('ShaderNodeVectorMath');mp.operation='MULTIPLY';mp.inputs[1].default_value=stretch;l.new(vector,mp.inputs[0]);vector=mp.outputs[0]
    tex=n.new('ShaderNodeTexNoise');tex.inputs['Scale'].default_value=scale;tex.inputs['Detail'].default_value=3;tex.inputs['Roughness'].default_value=.65;l.new(vector,tex.inputs['Vector'])
    return tex.outputs['Fac']


def range_value(n,l,value,lo,hi):
    node=n.new('ShaderNodeMapRange');node.inputs['To Min'].default_value=lo;node.inputs['To Max'].default_value=hi;l.new(value,node.inputs['Value']);return node.outputs['Result']


def bump(n,l,height,distance,strength,previous=None):
    node=n.new('ShaderNodeBump');node.inputs['Distance'].default_value=distance;node.inputs['Strength'].default_value=strength;l.new(height,node.inputs['Height'])
    if previous:l.new(previous,node.inputs['Normal'])
    return node.outputs['Normal']


def multiply_color(n,l,color,factor):
    node=n.new('ShaderNodeMixRGB');node.blend_type='MULTIPLY';node.inputs[0].default_value=1;node.inputs[1].default_value=(*color,1);l.new(factor,node.inputs[2]);return node.outputs[0]


def scan(n,l,root,kind,filename,vector,color=False):
    image=bpy.data.images.load(str(Path(root)/kind/filename),check_existing=True);image.colorspace_settings.name='sRGB' if color else 'Non-Color'
    node=n.new('ShaderNodeTexImage');node.image=image;node.projection='BOX';node.projection_blend=.15;node.extension='REPEAT';l.new(vector,node.inputs['Vector']);return node.outputs['Color']


def wood(root,planks=False):
    m,n,l,bs,tc,geo=material('ReferencePBR_oak_planks' if planks else 'ReferencePBR_oak_joinery',(.45,.30,.17),.44)
    vec=geo.outputs['Position'] if planks else tc.outputs['Object']
    mapped=n.new('ShaderNodeVectorMath');mapped.operation='MULTIPLY';mapped.inputs[1].default_value=(1.4,1.4,1.4);l.new(vec,mapped.inputs[0])
    color=scan(n,l,root,'wood_0002','base_color.jpg',mapped.outputs[0],True)
    bw=n.new('ShaderNodeRGBToBW');l.new(color,bw.inputs[0]);grain=range_value(n,l,bw.outputs[0],.66,1.20)
    l.new(multiply_color(n,l,(.46,.31,.18),grain),bs.inputs['Base Color'])
    rough=scan(n,l,root,'wood_0002','roughness.jpg',mapped.outputs[0]);l.new(range_value(n,l,rough,.28,.58),bs.inputs['Roughness'])
    fine=noise(n,l,vec,20,(8,.12,8));macro=noise(n,l,vec,1.6)
    normal=bump(n,l,macro,.00065,.18)
    normal=bump(n,l,bw.outputs[0],.00035,.5,normal)
    normal=bump(n,l,fine,.00016,.38,normal)
    if planks:
        brick=n.new('ShaderNodeTexBrick');brick.offset=.5;brick.offset_frequency=2
        brick.inputs['Scale'].default_value=1;brick.inputs['Brick Width'].default_value=1.20;brick.inputs['Row Height'].default_value=.18;brick.inputs['Mortar Size'].default_value=.0016;brick.inputs['Mortar Smooth'].default_value=.001
        brick.inputs['Color1'].default_value=(.48,.33,.19,1);brick.inputs['Color2'].default_value=(.37,.25,.14,1);brick.inputs['Mortar'].default_value=(.16,.105,.055,1);l.new(vec,brick.inputs['Vector'])
        mix=n.new('ShaderNodeMixRGB');mix.blend_type='MULTIPLY';mix.inputs[0].default_value=1;l.new(brick.outputs['Color'],mix.inputs[1]);l.new(grain,mix.inputs[2]);l.new(mix.outputs[0],bs.inputs['Base Color'])
        inv=n.new('ShaderNodeMath');inv.operation='SUBTRACT';inv.inputs[0].default_value=1;l.new(brick.outputs['Fac'],inv.inputs[1]);normal=bump(n,l,inv.outputs[0],.0008,.45,normal)
    l.new(normal,bs.inputs['Normal']);bs.inputs['Coat Weight'].default_value=.06;bs.inputs['Coat Roughness'].default_value=.38
    m['reference_pbr_kind']='wood';m['relief_scale_m']=.0008 if planks else .00035;return m


def carpet(albedo_image,root=None):
    m,n,l,bs,tc,geo=material('ReferencePBR_loop_pile_carpet',(.19,.20,.22),.88)
    mp=n.new('ShaderNodeVectorMath');mp.operation='SCALE';mp.inputs[3].default_value=.25;l.new(geo.outputs['Position'],mp.inputs[0])
    tx=n.new('ShaderNodeTexImage');tx.image=albedo_image;tx.interpolation='Linear';tx.extension='REPEAT';l.new(mp.outputs[0],tx.inputs['Vector']);l.new(tx.outputs['Color'],bs.inputs['Base Color'])
    coarse=noise(n,l,geo.outputs['Position'],150);fine=noise(n,l,geo.outputs['Position'],800)
    normal=None
    if root:
        fm=n.new('ShaderNodeVectorMath');fm.operation='SCALE';fm.inputs[3].default_value=4;l.new(geo.outputs['Position'],fm.inputs[0])
        nt=scan(n,l,root,'fabric_0022','normal_gl.png',fm.outputs[0]);nm=n.new('ShaderNodeNormalMap');nm.space='WORLD';nm.inputs['Strength'].default_value=.95;l.new(nt,nm.inputs['Color']);normal=nm.outputs['Normal']
        rough=scan(n,l,root,'fabric_0022','roughness.jpg',fm.outputs[0]);l.new(range_value(n,l,rough,.65,.97),bs.inputs['Roughness'])
        bc=scan(n,l,root,'fabric_0022','base_color.jpg',fm.outputs[0],True);bw=n.new('ShaderNodeRGBToBW');l.new(bc,bw.inputs[0])
        factor=range_value(n,l,bw.outputs[0],.72,1.35);mix=n.new('ShaderNodeMixRGB');mix.blend_type='MULTIPLY';mix.inputs[0].default_value=1;l.new(tx.outputs['Color'],mix.inputs[1]);l.new(factor,mix.inputs[2]);l.new(mix.outputs[0],bs.inputs['Base Color'])
    else:l.new(range_value(n,l,coarse,.74,.97),bs.inputs['Roughness'])
    normal=bump(n,l,coarse,.0010,.55,normal);normal=bump(n,l,fine,.00023,.4,normal);l.new(normal,bs.inputs['Normal'])
    bs.inputs['Sheen Weight'].default_value=.30;bs.inputs['Sheen Roughness'].default_value=.75;bs.inputs['Specular IOR Level'].default_value=.20
    m['reference_pbr_kind']='carpet';m['relief_scale_m']=.001;return m


def paint():
    m,n,l,bs,tc,geo=material('ReferencePBR_roller_painted_plaster',(.78,.765,.725),.68)
    slow=noise(n,l,geo.outputs['Position'],1.2);roller=noise(n,l,geo.outputs['Position'],210,(1,1,1.65));fine=noise(n,l,geo.outputs['Position'],750)
    l.new(multiply_color(n,l,(.78,.765,.725),range_value(n,l,slow,.97,1.025)),bs.inputs['Base Color'])
    l.new(range_value(n,l,roller,.56,.78),bs.inputs['Roughness'])
    normal=bump(n,l,slow,.0013,.2);normal=bump(n,l,roller,.00025,.45,normal);normal=bump(n,l,fine,.000055,.25,normal);l.new(normal,bs.inputs['Normal'])
    bs.inputs['Specular IOR Level'].default_value=.25;m['reference_pbr_kind']='paint';m['relief_scale_m']=.00025;return m


def brushed_metal(root):
    m,n,l,bs,tc,geo=material('ReferencePBR_brushed_stainless',(.53,.58,.62),.24,1)
    variation=noise(n,l,tc.outputs['Object'],8);striations=noise(n,l,tc.outputs['Object'],70,(1,60,1))
    l.new(range_value(n,l,variation,.16,.34),bs.inputs['Roughness'])
    l.new(bump(n,l,striations,.000045,.3),bs.inputs['Normal'])
    bs.inputs['Anisotropic'].default_value=.38;m['reference_pbr_kind']='bare_metal';m['relief_scale_m']=.000045;return m


def apply_office(root):
    oak=wood(root);planks=wood(root,True);wall=paint();metal=brushed_metal(root)
    cp=next(im for im in bpy.data.images if im.name.startswith('cp_'));floor_carpet=carpet(cp,root)
    changes=[];bevels=[]
    for o in bpy.data.objects:
        if o.type!='MESH':continue
        if o.name.endswith('.floor'):
            selected=planks if o.name.startswith(('hallway','kitchen')) else floor_carpet
            o.data.materials.clear();o.data.materials.append(selected);changes.append({'object':o.name,'material':selected.name})
        elif o.name.endswith('.wall'):
            o.data.materials.clear();o.data.materials.append(wall);changes.append({'object':o.name,'material':wall.name})
        else:
            for slot in o.material_slots:
                old=slot.material.name if slot.material else ''
                if old.startswith(('office02_reference_warm_oak','office02_reception_oak','office02_door_oak','ir_bench_top','ir_desk_top','ir_cred_oak','ir_conf_top')):
                    slot.material=oak;changes.append({'object':o.name,'material':oak.name,'previous':old})
                elif old.startswith(('office02_sink_steel','ir_chrome','office02_lift_steel')):
                    slot.material=metal;changes.append({'object':o.name,'material':metal.name,'previous':old})
            if o.name.startswith('Office02_') and o.get('audit_kind')!='vegetation' and not any(m.type=='BEVEL' for m in o.modifiers):
                if any(s.material in (oak,planks,metal) for s in o.material_slots):
                    bevel=o.modifiers.new('reference_physical_edge_rounding','BEVEL');bevel.width=.0012;bevel.segments=3;bevel.limit_method='ANGLE';bevels.append(o.name)
    return {'materials':[m.name for m in (oak,planks,wall,metal,floor_carpet)],'changes':changes,'actual_beveled_objects':bevels,'metallic_policy':'wood,carpet,paint0; bare steel1; painted frames retain dielectric finish','visual_acceptance':False}


def triplanar_normal(n,l,root,kind,position,normal,scale=2,strength=.25):
    """Blend scan-normal perturbations in world bases; flat map preserves N.

    No UV/tangent assumption on joined factory meshes. Three planar samples
    carry axis-specific tangent bases rather than treating RGB as world normal.
    """
    def vm(operation,a,b=None):
        node=n.new('ShaderNodeVectorMath');node.operation=operation;l.new(a,node.inputs[0])
        if b is not None:l.new(b,node.inputs[1])
        return node.outputs[0]
    def separate(vector):
        node=n.new('ShaderNodeSeparateXYZ');l.new(vector,node.inputs[0]);return list(node.outputs)
    def combine(values):
        node=n.new('ShaderNodeCombineXYZ')
        for i,value in enumerate(values):
            if isinstance(value,(int,float)):node.inputs[i].default_value=value
            else:l.new(value,node.inputs[i])
        return node.outputs[0]
    def scalar(operation,a,b=None):
        node=n.new('ShaderNodeMath');node.operation=operation;l.new(a,node.inputs[0])
        if b is not None:l.new(b,node.inputs[1])
        return node.outputs[0]
    mp=n.new('ShaderNodeVectorMath');mp.operation='SCALE';mp.inputs[3].default_value=scale;l.new(position,mp.inputs[0]);xyz=separate(mp.outputs[0]);ns=separate(normal)
    ab=vm('ABSOLUTE',normal);weights=vm('MULTIPLY',ab,ab);weights=vm('MULTIPLY',weights,weights);ws=separate(weights);total=scalar('ADD',scalar('ADD',ws[0],ws[1]),ws[2]);result=normal
    image=bpy.data.images.load(str(Path(root)/kind/'normal_gl.png'),check_existing=True);image.colorspace_settings.name='Non-Color'
    for axis,coords in enumerate([(xyz[1],xyz[2]),(xyz[0],xyz[2]),(xyz[0],xyz[1])]):
        tx=n.new('ShaderNodeTexImage');tx.image=image;tx.projection='FLAT';tx.extension='REPEAT';l.new(combine([*coords,0]),tx.inputs['Vector'])
        decode=n.new('ShaderNodeVectorMath');decode.operation='MULTIPLY_ADD';decode.inputs[1].default_value=(2,2,2);decode.inputs[2].default_value=(-1,-1,-2);l.new(tx.outputs['Color'],decode.inputs[0]);dx,dy,dz=separate(decode.outputs[0])
        signed=scalar('MULTIPLY',dz,scalar('SIGN',ns[axis]));oriented=combine([signed,dx,dy] if axis==0 else [dx,signed,dy] if axis==1 else [dx,dy,signed])
        weight=scalar('DIVIDE',ws[axis],total);weighted=n.new('ShaderNodeVectorMath');weighted.operation='SCALE';l.new(oriented,weighted.inputs[0]);l.new(weight,weighted.inputs[3]);amp=n.new('ShaderNodeVectorMath');amp.operation='SCALE';amp.inputs[3].default_value=strength;l.new(weighted.outputs[0],amp.inputs[0]);result=vm('ADD',result,amp.outputs[0])
    return vm('NORMALIZE',result)


def scanned_steel(root):
    m,n,l,bs,tc,geo=material('ReferencePBR_scanned_brushed_steel',(.53,.57,.59),.28,1)
    mp=n.new('ShaderNodeVectorMath');mp.operation='SCALE';mp.inputs[3].default_value=2;l.new(geo.outputs['Position'],mp.inputs[0])
    rough=scan(n,l,root,'metal_0038','roughness.jpg',mp.outputs[0]);l.new(range_value(n,l,rough,.24,.34),bs.inputs['Roughness'])
    l.new(triplanar_normal(n,l,root,'metal_0038',geo.outputs['Position'],geo.outputs['Normal'],2,.2),bs.inputs['Normal'])
    bs.inputs['Anisotropic'].default_value=.45;m['reference_pbr_kind']='bare_metal';return m
