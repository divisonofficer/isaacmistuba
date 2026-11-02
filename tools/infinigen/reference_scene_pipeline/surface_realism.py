"""Clean, material-specific macro/meso/micro irregularity in world metres."""
import bpy
from material_detail import material,noise,bump,range_value


def math_node(n,l,op,a,b=None,c=None):
    node=n.new('ShaderNodeMath');node.operation=op
    for index,value in enumerate((a,b,c)):
        if value is None:continue
        if isinstance(value,(int,float)):node.inputs[index].default_value=value
        else:l.new(value,node.inputs[index])
    return node.outputs[0]


def add(n,l,a,b):return math_node(n,l,'ADD',a,b)


def signed(n,l,value,amplitude):return math_node(n,l,'MULTIPLY_ADD',value,2*amplitude,-amplitude)


def clamp(n,l,value,lo,hi):return math_node(n,l,'MINIMUM',math_node(n,l,'MAXIMUM',value,lo),hi)


def color_scale(n,l,bs,factor):
    source=bs.inputs['Base Color'].links[0].from_socket if bs.inputs['Base Color'].links else None
    constant=tuple(bs.inputs['Base Color'].default_value);mix=n.new('ShaderNodeMixRGB');mix.blend_type='MULTIPLY';mix.inputs[0].default_value=1;mix.inputs[1].default_value=constant
    if source:l.new(source,mix.inputs[1])
    l.new(factor,mix.inputs[2]);l.new(mix.outputs[0],bs.inputs['Base Color'])


def enrich(m,kind):
    if m.get('multiscale_surface'):return None
    n=m.node_tree.nodes;l=m.node_tree.links;bs=next((x for x in n if x.type=='BSDF_PRINCIPLED'),None)
    if bs is None:return None
    geo=n.new('ShaderNodeNewGeometry');position=geo.outputs['Position']
    macro=noise(n,l,position,1.2);meso=noise(n,l,position,24,(1,1.6,1));micro=noise(n,l,position,950)
    old_rough=bs.inputs['Roughness'].links[0].from_socket if bs.inputs['Roughness'].links else bs.inputs['Roughness'].default_value
    normal=bs.inputs['Normal'].links[0].from_socket if bs.inputs['Normal'].links else None
    defaults={'paint':(.67,.03,.025,.008),'glazed_ceramic':(.13,.015,.010,.004),'glass':(.012,.003,.003,.001),'wood':(None,.035,.025,.007),'bare_metal':(None,.002,.001,.0004),'carpet':(None,.035,.025,.008),'textile':(None,.025,.02,.006),'stone':(.32,.035,.025,.008),'floor_stone':(.43,.035,.03,.008)}
    base,amp_macro,amp_meso,amp_micro=defaults[kind];rough=old_rough if base is None else base
    for value,amp in ((macro,amp_macro),(meso,amp_meso),(micro,amp_micro)):rough=add(n,l,rough,signed(n,l,value,amp))
    if kind=='glass':
        # Sparse, faint water-film response. No opaque dirt in glass albedo.
        stain=noise(n,l,position,11,(.6,.6,1.7));mask=range_value(n,l,stain,.38,.75)
        mask=clamp(n,l,math_node(n,l,'MULTIPLY',add(n,l,mask,-.57),1/.13),0,1)
        mask=math_node(n,l,'MULTIPLY',math_node(n,l,'MULTIPLY',mask,mask),math_node(n,l,'MULTIPLY_ADD',mask,-2,3))
        rough=add(n,l,rough,math_node(n,l,'MULTIPLY',mask,.045));bs.inputs['Metallic'].default_value=0;bs.inputs['Transmission Weight'].default_value=1;bs.inputs['IOR'].default_value=1.45
        normal=bump(n,l,meso,.000004,.12,normal)
    elif kind=='glazed_ceramic':
        for link in list(bs.inputs['Base Color'].links):l.remove(link)
        bs.inputs['Base Color'].default_value=(.88,.875,.85,1);bs.inputs['Metallic'].default_value=0;bs.inputs['IOR'].default_value=1.45
        normal=bump(n,l,meso,.000035,.14);normal=bump(n,l,micro,.000007,.18,normal)
    elif kind=='paint':
        normal=bump(n,l,macro,.0006,.15);normal=bump(n,l,meso,.000055,.25,normal);normal=bump(n,l,micro,.00004,.35,normal)
    elif kind=='wood':
        bs.inputs['Coat Weight'].default_value=.22
        coat=add(n,l,.18,signed(n,l,macro,.02));coat=add(n,l,coat,signed(n,l,meso,.012));l.new(coat,bs.inputs['Coat Roughness'])
        # Grain normal is retained, broad varnish variation is independent.
        normal=bump(n,l,macro,.00012,.10,normal)
    elif kind=='bare_metal':
        bs.inputs['Metallic'].default_value=1;bs.inputs['Anisotropic'].default_value=.5
    elif kind in ('stone','floor_stone'):
        normal=bump(n,l,meso,.00007,.18,normal);normal=bump(n,l,micro,.000025,.25,normal)
    if kind not in ('glass','bare_metal'):
        factor=add(n,l,1,signed(n,l,macro,.012));factor=add(n,l,factor,signed(n,l,meso,.006));color_scale(n,l,bs,factor)
    l.new(clamp(n,l,rough,.003,.98),bs.inputs['Roughness'])
    if normal:l.new(normal,bs.inputs['Normal'])
    m['multiscale_surface']=True;m['reference_pbr_kind']=kind
    return {'material':m.name,'kind':kind,'macro_scale_m':1/1.2,'meso_scale_m':1/24,'micro_scale_m':1/950,'roughness_amplitudes':[amp_macro,amp_meso,amp_micro],'coat_weight':.22 if kind=='wood' else 0}


def glazed_ceramic():
    m,*_=material('Realism_glazed_warm_white',(.88,.875,.85),.13);enrich(m,'glazed_ceramic');return m


def tile_material(name,color,roughness):
    m,n,l,bs,tc,geo=material(name,color,roughness);position=geo.outputs['Position']
    macro=noise(n,l,position,1.1);meso=noise(n,l,position,22);micro=noise(n,l,position,900)
    info=n.new('ShaderNodeObjectInfo');random=info.outputs['Random'];tone=add(n,l,1,signed(n,l,random,.025));tone=add(n,l,tone,signed(n,l,macro,.012));color_scale(n,l,bs,tone)
    rough=add(n,l,roughness,signed(n,l,random,.025))
    for value,amp in ((macro,.035),(meso,.025),(micro,.006)):rough=add(n,l,rough,signed(n,l,value,amp))
    l.new(clamp(n,l,rough,.18,.75),bs.inputs['Roughness']);normal=bump(n,l,meso,.000055,.18);normal=bump(n,l,micro,.000022,.24,normal);l.new(normal,bs.inputs['Normal'])
    m['multiscale_surface']=True;m['reference_pbr_kind']='tile';return m


def grout_material(name,color):
    m,n,l,bs,tc,geo=material(name,color,.77);macro=noise(n,l,geo.outputs['Position'],2);meso=noise(n,l,geo.outputs['Position'],55);micro=noise(n,l,geo.outputs['Position'],650)
    l.new(add(n,l,.77,signed(n,l,meso,.06)),bs.inputs['Roughness']);color_scale(n,l,bs,add(n,l,1,signed(n,l,macro,.025)));l.new(bump(n,l,micro,.00014,.35),bs.inputs['Normal']);m['multiscale_surface']=True;m['reference_pbr_kind']='grout';return m
