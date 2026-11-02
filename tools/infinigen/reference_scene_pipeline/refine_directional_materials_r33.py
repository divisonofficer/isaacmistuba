"""Material-only correction from actual texture orientation and closeup visibility evidence."""
import bpy,json,hashlib,math
from pathlib import Path
from material_detail import material,scan,range_value
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r32.blend';out=base/'scene_candidate_r33.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));assets=ref/'pbr_assets';changes=[]
fab=bpy.data.materials['BreakoutR30_fine_blue_upholstery'];bs=next(n for n in fab.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
for node in fab.node_tree.nodes:
 if node.type=='VECT_MATH' and node.operation=='SCALE' and not node.inputs[3].is_linked:
  if abs(node.inputs[3].default_value-9)<1e-5:node.inputs[3].default_value=5
  elif abs(node.inputs[3].default_value-.25)<1e-5:node.inputs[3].default_value=.18
 if node.type=='MAP_RANGE':
  if abs(node.inputs['To Min'].default_value-.96)<1e-5:node.inputs['From Min'].default_value=.15;node.inputs['From Max'].default_value=.80;node.inputs['To Min'].default_value=.75;node.inputs['To Max'].default_value=1.15;node.clamp=True
  elif abs(node.inputs['To Min'].default_value-.78)<1e-5:node.inputs['To Min'].default_value=.76;node.inputs['To Max'].default_value=.86
# Scan images are horizontal-grained: u must run along world/local Z on a vertical veneered door and along the leg.
m,n,l,bs,tc,geo=material('BreakoutR33_vertical_oak_veneer',(.48,.30,.16),.36);uv=tc.outputs['UV'];basecolor=scan(n,l,assets,'wood_0054','base_color.jpg',uv,True);l.new(basecolor,bs.inputs['Base Color']);rough=scan(n,l,assets,'wood_0054','roughness.jpg',uv);l.new(range_value(n,l,rough,.28,.45),bs.inputs['Roughness']);normal=scan(n,l,assets,'wood_0054','normal_gl.png',uv);nm=n.new('ShaderNodeNormalMap');nm.inputs['Strength'].default_value=.14;l.new(normal,nm.inputs['Color']);l.new(nm.outputs[0],bs.inputs['Normal']);bs.inputs['Coat Weight'].default_value=.15;bs.inputs['Coat Roughness'].default_value=.20;m['reference_pbr_kind']='wood'
for index,o in enumerate(sorted(bpy.data.objects,key=lambda x:x.name)):
 key=o.get('program_key','')
 if o.type!='MESH':continue
 if key in ['coffee_cabinet_front','coffee_upper_front']:
  o.data.materials.clear();o.data.materials.append(m);layer=o.data.uv_layers.active or o.data.uv_layers.new(name='Veneer_grain_metres');offset=(index*.173)%1
  for f in o.data.polygons:
   for li in f.loop_indices:
    p=o.data.vertices[o.data.loops[li].vertex_index].co
    layer.data[li].uv=(p.z*.70+offset,p.y*.70+(index*.327)%1) if abs(f.normal.x)>.5 else (p.z*.70+offset,p.x*.70) if abs(f.normal.y)>.5 else (p.y*.70+offset,p.x*.70)
  changes.append({'door':o.name,'grain':'scan horizontalU mapped to physical verticalZ','roughness_range':[.28,.45]})
 if key.startswith('breakout_chair') and '_upholstery' not in key and o.data.uv_layers.active:
  for item in o.data.uv_layers.active.data:item.uv=(item.uv.y,item.uv.x)
  changes.append({'leg_parent':o.name,'grain':'UV swap: horizontal scan grain now runs along actual leg Z'})
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r33.json').write_text(json.dumps({'source':str(src),'candidate':str(out),'source_sha256':sha,'reason':'r32 cloth still smooth at1280px; scan thumbnails show horizontal grain, proving prior leg UV mapping was circumferential. Reference cabinet fronts have vertical veneer.','changes':changes,'cloth':'20cm scan repeat, restrained .18 normal, real albedo contrast preserved rather than squeezed into8percent; no larger dirt/noise','geometry_lighting_exposure':'unchanged','photorealism_accepted':False},indent=2));print('SAVED',out)
