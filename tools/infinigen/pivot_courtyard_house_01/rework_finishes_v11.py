"""Continuous leafy borders, restrained oak grain, and stone porch detail."""
import bpy,json,random
from pathlib import Path
R=Path(__file__).resolve().parents[3];B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full';changed=[]
# Keep the same above-ground heights while increasing canopy overlap and burying
# the oversized lower trunk/root section inside the actual soil beds.
meta=json.loads((B/'leafy_stage_v9.json').read_text())
for row in meta['plants']:
 if row['root'].startswith('PivotLeafyV9_planter'):continue
 o=bpy.data.objects[row['root']];h=row['target_height'];o.scale*=1.6;o.location.z-=.6*h;changed.append({'root':o.name,'height_before':h,'canopy_scale_factor':1.6,'root_burial_m':.6*h})
calm=bpy.data.materials['pivot_r16_residential_oak'];swapped=[]
for o in bpy.data.objects:
 if o.type!='MESH':continue
 for slot in o.material_slots:
  if slot.material and slot.material.name in ['layout_v2_oak','entry_v4_oak','pantry_v2_oak']:
   swapped.append(o.name);slot.material=calm
# Dedicated mildly varied limestone on porch pier and vessels, without global room changes.
m=bpy.data.materials['pivot_r14_limestone'].copy();m.name='entry_v11_limestone';m.use_nodes=True;nt=m.node_tree;bs=nt.nodes.get('Principled BSDF');noise=nt.nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=7;noise.inputs['Detail'].default_value=3;ramp=nt.nodes.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].color=(.36,.32,.25,1);ramp.color_ramp.elements[1].color=(.56,.51,.42,1);nt.links.new(noise.outputs['Fac'],ramp.inputs[0]);nt.links.new(ramp.outputs['Color'],bs.inputs['Base Color']);bump=nt.nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.14;bump.inputs['Distance'].default_value=.025;nt.links.new(noise.outputs['Fac'],bump.inputs['Height']);nt.links.new(bump.outputs['Normal'],bs.inputs['Normal'])
for o in bpy.data.objects:
 if o.name.startswith(('PivotEntryV4_stone_pier','PivotEntryV6_HollowPlanter_')):
  for s in o.material_slots:s.material=m
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_finishes_v11.blend'))
(B/'finishes_stage_v11.json').write_text(json.dumps({'status':'geometry_saved_visual_review_pending','border_changes':changed,'subtle_oak_objects':sorted(set(swapped)),'stone_detail':'Dedicated entry pier/planter limestone','remaining':['Direct visual review of foliage continuity and above-ground botanical scale','No acceptance until all four original views and global regressions inspected']},indent=2)+'\n');print('PIVOT_FINISHES_V11_SAVED',flush=True)
