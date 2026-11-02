"""Readable pantry stone and garage concrete, isolated from other room materials."""
import bpy,json
from pathlib import Path
R=Path(__file__).resolve().parents[3];B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full'
def mineral(name,low,high,coarse,fine,rough):
    m=bpy.data.materials.new(name);m.use_nodes=True;nt=m.node_tree;p=nt.nodes['Principled BSDF'];tc=nt.nodes.new('ShaderNodeTexCoord')
    n=nt.nodes.new('ShaderNodeTexNoise');n.inputs['Scale'].default_value=coarse;n.inputs['Detail'].default_value=3;nt.links.new(tc.outputs['Object'],n.inputs['Vector'])
    ramp=nt.nodes.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].position=.25;ramp.color_ramp.elements[0].color=(*low,1);ramp.color_ramp.elements[1].position=.75;ramp.color_ramp.elements[1].color=(*high,1);nt.links.new(n.outputs['Fac'],ramp.inputs[0]);nt.links.new(ramp.outputs['Color'],p.inputs['Base Color'])
    grain=nt.nodes.new('ShaderNodeTexNoise');grain.inputs['Scale'].default_value=fine;grain.inputs['Detail'].default_value=2;nt.links.new(tc.outputs['Object'],grain.inputs['Vector'])
    bump=nt.nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.22;bump.inputs['Distance'].default_value=.0015;nt.links.new(grain.outputs['Fac'],bump.inputs['Height']);nt.links.new(bump.outputs['Normal'],p.inputs['Normal'])
    rr=nt.nodes.new('ShaderNodeMapRange');rr.inputs['To Min'].default_value=rough-.10;rr.inputs['To Max'].default_value=rough+.12;nt.links.new(grain.outputs['Fac'],rr.inputs['Value']);nt.links.new(rr.outputs['Result'],p.inputs['Roughness'])
    return m
stone=mineral('pantry_v33_warm_grey_mineral',(.20,.19,.17),(.42,.40,.355),9,120,.43)
changed=[]
for o in bpy.data.objects:
    if o.type!='MESH' or o.get('ir_room')!='utility_0/1':continue
    for slot in o.material_slots:
        if slot.material and slot.material.name in ['pivot_r14_limestone','pantry_v19_grey_stone','ir_counter_top_white_stone']:
            slot.link='OBJECT';slot.material=stone;changed.append(o.name)
assert changed,'No pantry stone surfaces found'
floor=bpy.data.objects['garage_0/0.floor'];floor.data.materials.clear();floor.data.materials.append(mineral('garage_v33_fine_mottled_concrete',(.20,.215,.22),(.37,.38,.37),14,145,.37))
bpy.context.view_layer.update();lights=[]
for o in bpy.data.objects:
    if o.type!='LIGHT':continue
    p=o.matrix_world.translation
    if 26.5<p.x<33 and 9<p.y<14:
        before=o.data.energy;o.data=o.data.copy();o.data.energy*=1.6;lights.append({'name':o.name,'before':before,'after':o.data.energy})
bpy.context.scene['pivot_revision']='quality_rework_v33_material_candidate';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_integrated_v33.blend'))
(B/'stone_concrete_v33.json').write_text(json.dumps({'status':'saved_original_views_pending','source':'scene_rework_integrated_v32.blend','pantry_surfaces':sorted(set(changed)),'garage_local_lights':lights,'changes':['Distinct grey mineral stone on pantry surfaces only','Concrete fine grain, tonal mottling and variable roughness','Local garage illumination increase, other rooms unchanged'],'remaining':['Direct same-camera review of stone/concrete readability','Full-scene latest render/plan/package/inspection consistency']},ensure_ascii=False,indent=2)+'\n');print('PIVOT_STONE_CONCRETE_V33_SAVED',len(changed),lights,flush=True)
