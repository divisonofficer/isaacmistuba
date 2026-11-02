"""Fix observable garage material/function, glass wall thickness and entry door clearances."""
import bpy,json,sys
from pathlib import Path
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools/infinigen'))
from room_planner import proc_assets as pa
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full'
m=bpy.data.materials.new('garage_v12_grey_concrete');m.use_nodes=True;nt=m.node_tree;p=nt.nodes['Principled BSDF'];p.inputs['Roughness'].default_value=.65;n=nt.nodes.new('ShaderNodeTexNoise');n.inputs['Scale'].default_value=4;n.inputs['Detail'].default_value=2;r=nt.nodes.new('ShaderNodeValToRGB');r.color_ramp.elements[0].color=(.19,.205,.215,1);r.color_ramp.elements[1].color=(.27,.285,.29,1);nt.links.new(n.outputs['Fac'],r.inputs[0]);nt.links.new(r.outputs['Color'],p.inputs['Base Color']);fine=nt.nodes.new('ShaderNodeTexNoise');fine.inputs['Scale'].default_value=110;bump=nt.nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.12;bump.inputs['Distance'].default_value=.002;nt.links.new(fine.outputs['Fac'],bump.inputs['Height']);nt.links.new(bump.outputs['Normal'],p.inputs['Normal']);floor=bpy.data.objects['garage_0/0.floor'];floor.data.materials.clear();floor.data.materials.append(m)
steel=bpy.data.materials['layout_v2_steel'];dark=bpy.data.materials['layout_v2_dark_frame']
def box(c,s):return ('box',c,s,(0,0,0))
parts=[box((29.8,y,2.48),(3.8,.045,.055)) for y in [9.46,13.54]]+[box((x,y,2.55),(.04,.04,.14)) for x in [28.1,31.3] for y in [9.46,13.54]]+[box((30.0,11.5,2.46),(2.8,.04,.045))]
o=pa._prims('PivotGarageV12_tracks_and_drive',[(steel,parts),(dark,[box((28.65,11.5,2.40),(.46,.32,.16))])]);o['ir_room']='garage_0/0'
# Hollow pantry jars: replace 17mm walls with actual 2.5mm glass and 4mm bottom.
for i,(x,h) in enumerate([(18.48,.24),(18.76,.29),(19.05,.27)]):
 o=bpy.data.objects['PivotPantryV2_food_jar_'+str(i)];bottom=1.61504;radius=.085
 for j in range(7):
  rad=[0,radius,radius,radius,radius-.0025,radius-.0025,0][j];z=[bottom,bottom,bottom+h-.025,bottom+h,bottom+h,bottom+.004,bottom+.004][j]
  for k in range(64):
   import math
   o.data.vertices[j*64+k].co=(x+rad*math.cos(k*math.tau/64),9.31+rad*math.sin(k*math.tau/64),z)
# Settle contents onto the new glass bottom and fit lids onto the wider jar rim.
for i,x in enumerate([18.48,18.76,19.05]):
 content=bpy.data.objects['PivotPantryV2_contents_'+str(i)];dz=1.61904-min(v.co.z for v in content.data.vertices)
 for v in content.data.vertices:v.co.z+=dz
 lid=bpy.data.objects['PivotPantryV2_food_jar_'+str(i)+'_lid']
 for v in lid.data.vertices:
  v.co.x=x+(v.co.x-x)*1.08;v.co.y=9.31+(v.co.y-9.31)*1.08
# Door leaf: 10mm bottom gap, 15mm top gap, keeping the real pivot axis.
hinge=bpy.data.objects['PivotEntryV4_physical_hinge'];hinge.location.z=.15555;leaf=bpy.data.objects['PivotEntryV4_open_oak_pivot_door']
for v in leaf.data.vertices:v.co.z*=2.38/2.34
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_physical_v12.blend'))
(B/'physical_stage_v12.json').write_text(json.dumps({'status':'geometry_saved_visual_review_pending','changes':['Grey fine concrete garage floor instead of beige stone/carpet appearance','Ceiling sectional-door guide rails, supports and drive motor','Pantry jar walls 2.5mm and bottom 4mm','Entry pivot leaf bottom gap 10mm and corrected top clearance'],'remaining':['Inspect original four cameras','Verify tracks and gate clearance from supplemental garage view','Check glass readability, jar lid fit and door clearances in final geometry audit']},indent=2)+'\n');print('PIVOT_PHYSICAL_V12_SAVED',flush=True)
