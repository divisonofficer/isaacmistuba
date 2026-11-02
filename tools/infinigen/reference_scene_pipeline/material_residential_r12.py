"""Audit actual assignments and add omitted sofa/chair textile detail."""
import bpy,json,shutil
from pathlib import Path
from material_detail import scan,noise,bump,range_value
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';assets=ref/'pbr_assets/fabric_0022'
assets.mkdir(parents=True,exist_ok=True)
for name in ('base_color.jpg','roughness.jpg','normal_gl.png'):
 dest=assets/name
 if not dest.exists():shutil.copy2(ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/pbr_assets/fabric_0022'/name,dest)
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r11.blend'))
textiles=[];metals=[];stones=[]
for m in bpy.data.materials:
 if not m.use_nodes:continue
 n=m.node_tree.nodes;l=m.node_tree.links;bs=next((x for x in n if x.type=='BSDF_PRINCIPLED'),None)
 if not bs:continue
 textile=m.name.startswith(('ir_sfb_cream','ir_sfb_white','ir_sfb_throw','ir_sfb_oat','ir_sfb_greige','ir_sfb_petrol','ir_sec_fabric','ir_sec_cushion','ir_sec_pillow','ir_wdc_fabric','res03_rug_linen','res03_sheer_linen'))
 metal=m.name.startswith(('res03_lift_steel','res03_lamp_brass','ir_chrome','ir_kit_steel','ir_kit_fridge'))
 stone=m.name.startswith(('ir_sdt_stone','ir_sct_stone','ir_kit_top'))
 if not (textile or metal or stone):continue
 geo=n.new('ShaderNodeNewGeometry')
 if textile:
  mp=n.new('ShaderNodeVectorMath');mp.operation='SCALE';mp.inputs[3].default_value=3;l.new(geo.outputs['Position'],mp.inputs[0])
  color=scan(n,l,ref/'pbr_assets','fabric_0022','base_color.jpg',mp.outputs[0],True)
  bw=n.new('ShaderNodeRGBToBW');l.new(color,bw.inputs[0]);height=bw.outputs[0]
  # Preserve the existing selected textile colour or its upstream colour graph.
  original=bs.inputs['Base Color'].links[0].from_socket if bs.inputs['Base Color'].links else None;constant=tuple(bs.inputs['Base Color'].default_value)
  mix=n.new('ShaderNodeMixRGB');mix.blend_type='MULTIPLY';mix.inputs[0].default_value=1;mix.inputs[1].default_value=constant
  if original:l.new(original,mix.inputs[1])
  l.new(range_value(n,l,height,.78,1.20),mix.inputs[2]);l.new(mix.outputs[0],bs.inputs['Base Color'])
  rough=scan(n,l,ref/'pbr_assets','fabric_0022','roughness.jpg',mp.outputs[0]);l.new(range_value(n,l,rough,.65,.95),bs.inputs['Roughness'])
  l.new(bump(n,l,height,.0007,.65),bs.inputs['Normal']);bs.inputs['Sheen Weight'].default_value=.25;bs.inputs['Metallic'].default_value=0;textiles.append(m.name)
 elif metal:
  f=noise(n,l,geo.outputs['Position'],35,(1,12,1));l.new(range_value(n,l,f,.22,.34),bs.inputs['Roughness']);l.new(bump(n,l,f,.000018,.25),bs.inputs['Normal']);bs.inputs['Metallic'].default_value=1;bs.inputs['Anisotropic'].default_value=.4;metals.append(m.name)
 elif stone:
  f=noise(n,l,geo.outputs['Position'],90);l.new(range_value(n,l,f,.18,.32),bs.inputs['Roughness']);l.new(bump(n,l,f,.00012,.28),bs.inputs['Normal']);bs.inputs['Metallic'].default_value=0;stones.append(m.name)
assert any(x.startswith('ir_sec_fabric') for x in textiles),'Actual sofa upholstery missing'
assert any(x.startswith('ir_wdc_fabric') for x in textiles),'Actual dining-chair upholstery missing'
records=[]
for o in bpy.data.objects:
 if o.type!='MESH' or o.get('reference_scene_owner')!='dual_unit_residential_floor_03':continue
 for slot in o.material_slots:
  m=slot.material
  if m and m.name in textiles+metals+stones:records.append({'object':o.name,'material':m.name,'kind':'textile' if m.name in textiles else 'bare_metal' if m.name in metals else 'stone'})
out=base/'scene_candidate_r12.blend';assert not out.exists();bpy.ops.wm.save_as_mainfile(filepath=str(out))
(ref/'material_detail_r12.json').write_text(json.dumps({'source':'scene_candidate_r11.blend','textiles':textiles,'bare_metals':metals,'stones':stones,'actual_object_assignments':records,'normal_method':'Textile height from scan luminance through metre-scale bump; no unsupported tangent-space normal mapping on arbitrary factory meshes.','visual_acceptance':False},indent=2))
