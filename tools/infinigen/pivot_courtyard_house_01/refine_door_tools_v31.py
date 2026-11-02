"""Dedicated warm oak door surface and identifiable wall-mounted garage tools."""
import bpy, math, json, sys
from pathlib import Path
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools/infinigen'))
from room_planner import proc_assets as pa
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full'
def mat(name,c,rough=.55,metal=0):
    m=bpy.data.materials.new(name);m.use_nodes=True;p=m.node_tree.nodes['Principled BSDF'];p.inputs['Base Color'].default_value=(*c,1);p.inputs['Roughness'].default_value=rough;p.inputs['Metallic'].default_value=metal;return m
oak=mat('entry_v31_dedicated_warm_oak',(.32,.17,.065))
nt=oak.node_tree;bs=nt.nodes['Principled BSDF'];tc=nt.nodes.new('ShaderNodeTexCoord');vec=nt.nodes.new('ShaderNodeVectorMath');vec.operation='MULTIPLY';vec.inputs[1].default_value=(20,12,.65);nt.links.new(tc.outputs['Object'],vec.inputs[0]);noise=nt.nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=3;noise.inputs['Detail'].default_value=3;nt.links.new(vec.outputs['Vector'],noise.inputs['Vector']);ramp=nt.nodes.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].color=(.19,.085,.025,1);ramp.color_ramp.elements[1].color=(.39,.23,.10,1);nt.links.new(noise.outputs['Fac'],ramp.inputs[0]);nt.links.new(ramp.outputs['Color'],bs.inputs['Base Color']);bump=nt.nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.12;bump.inputs['Distance'].default_value=.0006;nt.links.new(noise.outputs['Fac'],bump.inputs['Height']);nt.links.new(bump.outputs['Normal'],bs.inputs['Normal'])
door=bpy.data.objects['PivotEntryV4_open_oak_pivot_door'];replaced=[]
for slot in door.material_slots:
    if slot.material and 'dark' not in slot.material.name.lower():
        replaced.append(slot.material.name);slot.link='OBJECT';slot.material=oak
assert replaced,'Door wood slot not found'
steel=mat('garage_v31_brushed_tool_steel',(.31,.34,.36),.30,.85);rubber=mat('garage_v31_grip',(.025,.032,.033),.78)
def box(c,s,r=0):return ('box',c,s,(0,r,0))
def build(i,groups):
    old=bpy.data.objects['PivotStorageV5_wall_tool_'+str(i)];bpy.data.objects.remove(old,do_unlink=True)
    o=pa._prims('PivotGarageV31_wall_tool_'+str(i),groups);o['ir_room']='garage_0/0';return o
# Screwdriver: handle, narrow shaft, flattened blade.
x=28.48;build(1,[(rubber,[box((x,9.235,1.56),(.048,.04,.17))]),(steel,[box((x,9.235,1.735),(.012,.012,.19)),box((x,9.235,1.845),(.022,.006,.035))])])
# Combination spanner with visibly open jaw and closed ring.
x=28.76;build(2,[(steel,[box((x,9.235,1.67),(.033,.018,.30)),box((x-.038,9.235,1.85),(.024,.025,.08),-.25),box((x+.038,9.235,1.85),(.024,.025,.08),.25),box((x,9.235,1.815),(.08,.025,.025))])])
bpy.ops.mesh.primitive_torus_add(major_radius=.035,minor_radius=.009,major_segments=32,minor_segments=8,location=(x,9.235,1.50),rotation=(math.pi/2,0,0));o=bpy.context.object;o.name='PivotGarageV31_spanner_ring';o.data.materials.append(steel);o['ir_room']='garage_0/0'
# Pliers: two grips and opposing jaws, joined at the pivot.
x=29.04;build(3,[(rubber,[box((x-.035,9.235,1.57),(.027,.036,.17),-.22),box((x+.035,9.235,1.57),(.027,.036,.17),.22)]),(steel,[box((x-.025,9.235,1.74),(.025,.022,.13),.23),box((x+.025,9.235,1.74),(.025,.022,.13),-.23),('sph',(x,9.235,1.68),(.037,.018,.035),(0,0,0))])])
# Garden trowel: tapered rounded blade and separate handle/shank.
x=29.32;build(4,[(rubber,[box((x,9.235,1.80),(.042,.035,.15))]),(steel,[box((x,9.235,1.685),(.015,.015,.10)),('sph',(x,9.235,1.565),(.055,.013,.09),(0,0,0))])])
hooks=[box((x,9.215,1.92),(.035,.045,.018)) for x in [28.48,28.76,29.04,29.32]]
o=pa._prims('PivotGarageV31_tool_board_hooks',[(steel,hooks)]);o['ir_room']='garage_0/0'
bpy.context.view_layer.update();bpy.context.scene['pivot_revision']='quality_rework_v31_door_tools_candidate';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_integrated_v31.blend'))
(B/'door_tools_v31.json').write_text(json.dumps({'status':'saved_original_view_visual_review_pending','source_scene':'scene_rework_integrated_v30.blend','door_wood_slots_replaced':replaced,'changes':['Dedicated warm vertical oak grain on door only; hinge and clearance unchanged','Screwdriver, combination spanner, pliers and garden trowel replace undifferentiated sticks','Board mounting hooks'],'remaining':['Actual visual readability from frozen garage and entry cameras','Tool support and current physical audit','All-space final consistency']},ensure_ascii=False,indent=2)+'\n');print('PIVOT_DOOR_TOOLS_V31_SAVED',flush=True)
