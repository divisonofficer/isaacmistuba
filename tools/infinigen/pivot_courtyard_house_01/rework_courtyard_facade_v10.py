"""Open the former kitchen/family dining facade onto courtyard; preserve the original camera."""
import bpy,bmesh,json,sys
from pathlib import Path
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools/infinigen'))
from room_planner import proc_assets as pa
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full';dark=bpy.data.materials['layout_v2_dark_frame'];glass=bpy.data.materials['layout_v2_glazing'];oak=bpy.data.materials['layout_v2_oak'];stone=bpy.data.materials['pivot_r14_limestone']
def box(c,s):return ('box',c,s,(0,0,0))
def create(n,groups):
 o=pa._prims('PivotCourtyardV10_'+n,groups);o['ir_room']='dining-room_0/1';return o
caps=[]
for suffix in ['.wall','.exterior']:
 o=bpy.data.objects['dining-room_0/1'+suffix]
 bpy.ops.mesh.primitive_cube_add(size=1,location=(13.5,9,1.37));c=bpy.context.object;c.dimensions=(5.4,.8,2.45);bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);mod=o.modifiers.new('family_courtyard_opening','BOOLEAN');mod.operation='DIFFERENCE';mod.solver='EXACT';mod.object=c;bpy.context.view_layer.objects.active=o;bpy.ops.object.modifier_apply(modifier=mod.name);bpy.data.objects.remove(c,do_unlink=True)
 bm=bmesh.new();bm.from_mesh(o.data);remove=[]
 for f in bm.faces:
  co=o.matrix_world@f.calc_center_median();n=o.matrix_world.to_3x3()@f.normal
  if min(abs(co.y-8.6),abs(co.y-9.4))<.003 and abs(n.y)>.98 and 10.79<co.x<16.21 and .14<co.z<2.60:remove.append(f)
 caps.append({'object':o.name,'removed_surface_caps':len(remove)});bmesh.ops.delete(bm,geom=remove,context='FACES');bm.to_mesh(o.data);bm.free()
xs=[10.8,12.15,13.5,14.85,16.2]
create('family_glazing_frames',[(dark,[box((x,9.015,1.37),(.045,.075,2.45)) for x in xs]+[box((13.5,9.015,z),(5.445,.075,.045)) for z in [.1675,2.5725]])])
create('family_glazing',[(glass,[box(((a+b)/2,9.015,1.37),(b-a-.045,.012,2.36)) for a,b in zip(xs[:-1],xs[1:])])])
# Breakfast counter against north wall leaves a full clear strip at glazing.
create('family_breakfast_counter',[(oak,[box((13.5,11.13,.57),(4.15,.48,.84))]+[box((11.45+(i+.5)*4.1/7,10.878,.57),(.57,.025,.79)) for i in range(7)]),(stone,[box((13.5,11.12,1.015),(4.25,.56,.05))])])
pa.STYLE['chair_style']='light_wood'
import math
for i,x in enumerate([12.15,13.5,14.85]):
 o=pa.CounterStoolFactory(48713010+i).spawn_asset(3010+i);o.location=(x,10.40,.14754);o.rotation_euler.z=math.pi/2;o['ir_room']='dining-room_0/1'
# Courtyard-facing eaves give glazing a recessed architectural edge.
create('courtyard_fascia',[(dark,[box((13.5,8.9,2.81),(6.1,.30,.055)),box((16.4,6.5,2.81),(.30,5.0,.055))])])
# Real-scale fine lawn variation, isolated from the surrounding terrain material.
m=bpy.data.materials['pivot_grass'];m.use_nodes=True;nt=m.node_tree;bs=nt.nodes.get('Principled BSDF');tex=nt.nodes.new('ShaderNodeTexNoise');tex.inputs['Scale'].default_value=150;tex.inputs['Detail'].default_value=2
ramp=nt.nodes.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].color=(.055,.10,.018,1);ramp.color_ramp.elements[1].color=(.18,.28,.065,1);nt.links.new(tex.outputs['Fac'],ramp.inputs[0]);nt.links.new(ramp.outputs['Color'],bs.inputs['Base Color']);bump=nt.nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.18;bump.inputs['Distance'].default_value=.008;nt.links.new(tex.outputs['Fac'],bump.inputs['Height']);nt.links.new(bump.outputs['Normal'],bs.inputs['Normal'])
bpy.context.view_layer.update();bpy.context.scene['pivot_revision']='courtyard_facade_v10_work_in_progress';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_facade_v10.blend'))
(B/'courtyard_facade_stage_v10.json').write_text(json.dumps({'status':'geometry_saved_visual_review_pending','changes':['Former kitchen / family dining south wall now actual full-height glazing','Breakfast counter and three stools facing courtyard','Dark roof-edge fascia and lawn surface detail'],'surface_caps':caps,'remaining':['Same original camera comparison','Family counter and dining connection clearance','Whole house regression and updated floorplan']},indent=2)+'\n');print('PIVOT_COURTYARD_V10_SAVED',flush=True)
