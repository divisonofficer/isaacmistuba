"""Use surface metre-scale UVs consistently on seat and back instead of world box projection."""
import bpy,json,hashlib
from pathlib import Path
from material_detail import material,range_value,multiply_color
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r38.blend';out=base/'scene_candidate_r39.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src))
m,n,l,bs,tc,geo=material('BreakoutR39_surface_mapped_blue_weave',(.055,.105,.155),.80)
def texture(filename,color=False):
 image=bpy.data.images.load(str(ref/'pbr_assets/fabric_0022'/filename),check_existing=True);image.colorspace_settings.name='sRGB' if color else 'Non-Color';t=n.new('ShaderNodeTexImage');t.image=image;t.projection='FLAT';t.extension='REPEAT';l.new(tc.outputs['UV'],t.inputs['Vector']);return t.outputs['Color']
color=texture('base_color.jpg',True);bw=n.new('ShaderNodeRGBToBW');l.new(color,bw.inputs[0]);factor=range_value(n,l,bw.outputs[0],.75,1.15);r=next(x for x in n if x.type=='MAP_RANGE');r.inputs['From Min'].default_value=.15;r.inputs['From Max'].default_value=.80;r.clamp=True;l.new(multiply_color(n,l,(.055,.105,.155),factor),bs.inputs['Base Color']);l.new(range_value(n,l,texture('roughness.jpg'),.76,.86),bs.inputs['Roughness']);nm=n.new('ShaderNodeNormalMap');nm.space='TANGENT';nm.inputs['Strength'].default_value=.18;l.new(texture('normal_gl.png'),nm.inputs['Color']);l.new(nm.outputs['Normal'],bs.inputs['Normal']);bs.inputs['Sheen Weight'].default_value=.14;bs.inputs['Specular IOR Level'].default_value=.25;m['reference_pbr_kind']='textile';rows=[]
for o in bpy.data.objects:
 key=o.get('program_key','')
 if o.type!='MESH' or not key.startswith('breakout_chair') or '_upholstery' not in key:continue
 o.data=o.data.copy();layer=o.data.uv_layers.active or o.data.uv_layers.new(name='Upholstery_metres_20cm_repeat');back='_back_' in key
 for poly in o.data.polygons:
  for li in poly.loop_indices:
   co=o.data.vertices[o.data.loops[li].vertex_index].co
   layer.data[li].uv=(co.y*o.scale.y*5,co.z*o.scale.z*5) if back else (co.x*o.scale.x*5,co.y*o.scale.y*5)
 o.data.materials.clear();o.data.materials.append(m);rows.append({'object':o.name,'surface':'back' if back else 'seat','mapping':'YZ' if back else 'XY','repeats_per_metre':5})
assert len(rows)==8
bpy.ops.wm.save_as_mainfile(filepath=str(out))
assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
(ref/'realism_refinement_r39.json').write_text(json.dumps({'source':str(src),'candidate':str(out),'source_sha256':sha,'trigger':'Direct and independent closeup: chair back textile reads stronger than smooth seat. Existing upholstery has no UVs and uses world box projection.','change':'8 shaped upholstery parts use same scan, physical20cm surface UV repeat and tangent-space normal; geometry/lighting/exposure unchanged','mapping':rows,'limitations':'Projection at thin side edges may stretch; inspect closeup before adoption. Same nominal tile scale is not proof of equal photographic response.','photorealism_accepted':False},indent=2));print('SAVED',out,flush=True)
