"""Isolate light versus shader contribution with identical geometry/camera/exposure."""
import bpy,json,hashlib,argparse
from pathlib import Path
from mathutils import Vector
from material_detail import material,scan,range_value,multiply_color,triplanar_normal
p=argparse.ArgumentParser();p.add_argument('--variant',choices=['B','C','C2'],required=True);a=p.parse_args();ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r27.blend';out=base/f'breakout_diagnostic_r28{a.variant}.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));changes=[]
if a.variant=='B':
 light=bpy.data.lights.new('Diagnostic_side_softbox','AREA');light.energy=80;light.shape='RECTANGLE';light.size=.65;light.size_y=1.8;o=bpy.data.objects.new(light.name,light);bpy.context.scene.collection.objects.link(o);o.location=(11.7,6.45,2.1);o.rotation_euler=(Vector((14.25,4.8,1.05))-o.location).to_track_quat('-Z','Y').to_euler();changes=['Only80W side area added. Diagnostic softbox, not a physically installed final luminaire.']
else:
 assets=ref/'pbr_assets'
 def scanned(name,kind,color,lo,hi,scale,amp):
  m,n,l,bs,tc,geo=material(name,color,(lo+hi)/2);mp=n.new('ShaderNodeVectorMath');mp.operation='SCALE';mp.inputs[3].default_value=scale;l.new(geo.outputs['Position'],mp.inputs[0]);basecolor=scan(n,l,assets,kind,'base_color.jpg',mp.outputs[0],True);bw=n.new('ShaderNodeRGBToBW');l.new(basecolor,bw.inputs[0]);l.new(multiply_color(n,l,color,range_value(n,l,bw.outputs[0],.78,1.13)),bs.inputs['Base Color']);rough=scan(n,l,assets,kind,'roughness.jpg',mp.outputs[0]);l.new(range_value(n,l,rough,lo,hi),bs.inputs['Roughness']);l.new(triplanar_normal(n,l,assets,kind,geo.outputs['Position'],geo.outputs['Normal'],scale,amp),bs.inputs['Normal']);return m
 oak=scanned('Diagnostic_scan_oak_alternative','wood_0002' if a.variant=='C2' else 'wood_0054',(.46,.31,.18),.27,.44,1,.13);fabric=scanned('Diagnostic_scan_blue_weave','fabric_0022',(.055,.105,.155),.65,.85,4,.32)
 bs=next(n for n in oak.node_tree.nodes if n.type=='BSDF_PRINCIPLED');bs.inputs['Coat Weight'].default_value=.18;bs.inputs['Coat Roughness'].default_value=.20
 for o in bpy.data.objects:
  key=o.get('program_key','')
  if o.type!='MESH':continue
  if key.startswith(('coffee_base','coffee_cabinet_front','coffee_upper')):
   for slot in o.material_slots:
    if slot.material and ('oak' in slot.material.name.lower() or slot.material.get('reference_pbr_kind')=='wood'):slot.material=oak;changes.append(o.name)
  if key.startswith('breakout_chair'):
   for slot in o.material_slots:
    if slot.material and ('fabric' in slot.material.name or slot.material.get('reference_pbr_kind')=='textile'):slot.material=fabric;changes.append(o.name)
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/f'breakout_diagnostic_r28{a.variant}.json').write_text(json.dumps({'variant':a.variant,'source':str(src),'source_sha256':sha,'candidate':str(out),'changes':changes,'scope':'B light only; C shader only. Existing local scanned PBR alternative; quality judged from render, not asserted.','photorealism_accepted':False},indent=2));print('SAVED',out,flush=True)
