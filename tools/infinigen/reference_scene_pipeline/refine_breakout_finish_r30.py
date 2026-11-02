"""Closeup-led correction: restrain fabric/leg relief and fix intersecting appliance panels."""
import bpy,json,math,hashlib
from pathlib import Path
from mathutils import Vector
from material_detail import material,scan,triplanar_normal,range_value,multiply_color
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r29.blend';out=base/'scene_candidate_r30.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));assets=ref/'pbr_assets';changes=[]
# The closeup revealed loop pile magnified into a heavy crinkled relief; use a denser physical repeat and low-amplitude normal.
m,n,l,bs,tc,geo=material('BreakoutR30_fine_blue_upholstery',(.055,.105,.155),.76);pos=n.new('ShaderNodeVectorMath');pos.operation='SCALE';pos.inputs[3].default_value=9;l.new(geo.outputs['Position'],pos.inputs[0]);albedo=scan(n,l,assets,'fabric_0022','base_color.jpg',pos.outputs[0],True);bw=n.new('ShaderNodeRGBToBW');l.new(albedo,bw.inputs[0]);l.new(multiply_color(n,l,(.055,.105,.155),range_value(n,l,bw.outputs[0],.96,1.04)),bs.inputs['Base Color']);rough=scan(n,l,assets,'fabric_0022','roughness.jpg',pos.outputs[0]);l.new(range_value(n,l,rough,.70,.82),bs.inputs['Roughness']);l.new(triplanar_normal(n,l,assets,'fabric_0022',geo.outputs['Position'],geo.outputs['Normal'],9,.10),bs.inputs['Normal']);bs.inputs['Sheen Weight'].default_value=.14;bs.inputs['Specular IOR Level'].default_value=.25;m['reference_pbr_kind']='textile'
wood,n,l,bs,tc,geo=material('BreakoutR30_sealed_oak_legs',(.48,.34,.20),.36);uv=tc.outputs['UV'];basecolor=scan(n,l,assets,'wood_0002','base_color.jpg',uv,True);bw=n.new('ShaderNodeRGBToBW');l.new(basecolor,bw.inputs[0]);l.new(multiply_color(n,l,(.48,.34,.20),range_value(n,l,bw.outputs[0],.8,1.15)),bs.inputs['Base Color']);rough=scan(n,l,assets,'wood_0002','roughness.jpg',uv);l.new(range_value(n,l,rough,.31,.43),bs.inputs['Roughness']);tx=scan(n,l,assets,'wood_0002','normal_gl.png',uv);nm=n.new('ShaderNodeNormalMap');nm.inputs['Strength'].default_value=.12;l.new(tx,nm.inputs['Color']);l.new(nm.outputs[0],bs.inputs['Normal']);bs.inputs['Coat Weight'].default_value=.18;bs.inputs['Coat Roughness'].default_value=.22;wood['reference_pbr_kind']='wood'
for o in bpy.data.objects:
 key=o.get('program_key','')
 if not key.startswith('breakout_chair') or o.type not in ('MESH','CURVE'):continue
 for slot in o.material_slots:
  if slot.material and ('fabric' in slot.material.name or slot.material.get('reference_pbr_kind')=='textile'):slot.material=m
  elif slot.material and slot.material.name.startswith('ir_wdc_oak'):slot.material=wood
 if o.type=='MESH' and key.startswith('breakout_chair') and ('_upholstery' not in key):
  uvdata=(o.data.uv_layers.active or o.data.uv_layers.new(name='Leg_cylindrical_metres')).data
  for f in o.data.polygons:
   for idx in f.loop_indices:
    co=o.data.vertices[o.data.loops[idx].vertex_index].co;cx=.2 if co.x>0 else -.2;cy=.2 if co.y>0 else -.2;u=math.atan2(co.y-cy,co.x-cx)/math.tau*.10;uvdata[idx].uv=(u,co.z)
 forkey=key;changes.append({'object':o.name,'response':'fine fabric or sealed leg wood; geometry preserved'})
# Disjoint panels meet at their boundary rather than overlapping through the header.
back=next(o for o in bpy.data.objects if o.get('program_key')=='coffee_machine');anchor=back.location.copy();anchor.x-=.09;z0=anchor.z-.155
for o in bpy.data.objects:
 key=o.get('program_key','')
 if key=='machine_side':
  sign=1 if o.location.y>anchor.y else -1;o.location=(anchor.x-.0525,anchor.y+sign*.192,z0+.135);o.dimensions=(.165,.016,.27)
 elif key=='machine_upper':o.location=(anchor.x-.0775,anchor.y,z0+.29);o.dimensions=(.215,.40,.04)
 elif key=='machine_control_panel':o.location=(anchor.x-.189,anchor.y,z0+.29);o.dimensions=(.008,.32,.032)
 elif key=='machine_button':o.location.x=anchor.x-.197;o.location.z=z0+.29
 if key.startswith('luminaire_'):o['reference_ceiling_detail']=True
 if key in ['machine_side','machine_upper','machine_control_panel']:
  for mod in o.modifiers:
   if mod.type=='BEVEL':mod.width=.0012;mod.segments=3
  changes.append({'object':o.name,'panel_joinery':'flush header and side boundaries; no coextensive intersecting corner faces'})
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r30.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'reason':'r29 closeup showed crinkled over-amplified fabric and circumferential leg relief; independent review noted appliance upper-corner wedge','changes':changes,'lighting':'unchanged from r29','photorealism_accepted':False},indent=2));print('SAVED',out,flush=True)
