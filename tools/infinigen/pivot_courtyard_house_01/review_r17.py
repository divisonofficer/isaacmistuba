"""Reduce visibly exaggerated oak grain and shade laundry door rings smoothly."""
import bpy,json,math
from pathlib import Path
R=Path(__file__).resolve().parents[3];B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full'
m=bpy.data.materials['pivot_r16_residential_oak'];n=m.node_tree.nodes;n.clear();l=m.node_tree.links
out=n.new('ShaderNodeOutputMaterial');bs=n.new('ShaderNodeBsdfPrincipled');bs.inputs['Roughness'].default_value=.57;l.new(bs.outputs['BSDF'],out.inputs['Surface'])
tc=n.new('ShaderNodeTexCoord');mapping=n.new('ShaderNodeVectorMath');mapping.operation='MULTIPLY';mapping.inputs[1].default_value=(4,4,.23);l.new(tc.outputs['Object'],mapping.inputs[0]);noise=n.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=9;noise.inputs['Detail'].default_value=2;l.new(mapping.outputs[0],noise.inputs['Vector']);ramp=n.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].color=(.43,.30,.18,1);ramp.color_ramp.elements[1].color=(.51,.38,.25,1);l.new(noise.outputs['Fac'],ramp.inputs[0]);l.new(ramp.outputs['Color'],bs.inputs['Base Color'])
count=0
for o in bpy.data.objects:
 if o.type=='MESH' and o.get('ir_role') in ('washing_machine','tumble_dryer'):
  for p in o.data.polygons:
   # Cylinder axes point along Y: curved wall normals vary in XZ, caps are +/-Y.
   if p.material_index in (1,2) and abs(p.normal.y)<.8:p.use_smooth=True;count+=1
# Pantry fronts and uppers must share the same calm oak, without changing appliances.
changed=[]
for o in bpy.data.objects:
 if o.type=='MESH' and o.get('ir_room')=='utility_0/1':
  for s in o.material_slots:
   if s.material and any(x in s.material.name.lower() for x in ('pantry_cab','pantry_wood','pantry_upper')):changed.append([o.name,s.material.name]);s.material=m
bpy.context.scene['pivot_revision']='r17_subtle_oak';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_review_r17.blend'))
(B/'revision_r17.json').write_text(json.dumps({'changes':['Replaced exaggerated periodic r16 oak grain with low-contrast elongated noise','Smooth shading only on laundry appliance cylindrical side faces'],'smoothed_faces':count,'pantry_material_changes':changed,'architecture_changed':False},indent=2));print('PIVOT_R17_COMPLETE',flush=True)
