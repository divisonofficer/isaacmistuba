"""Retain real native fabric, correct polished optical roles and WC hardware tags."""
import bpy,json,hashlib,math
from pathlib import Path
from material_detail import material,noise,bump,range_value
from surface_realism import enrich
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';source=base/'scene_candidate_r27.blend';out=base/'scene_candidate_r28.blend';assert not out.exists();before=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source));changes=[]
def polished(name,color,rough,variation):
 m,n,l,bs,tc,geo=material(name,color,rough,1);height=noise(n,l,geo.outputs['Position'],1200);l.new(range_value(n,l,height,rough-variation,rough+variation),bs.inputs['Roughness']);l.new(bump(n,l,height,.0000005,.05),bs.inputs['Normal']);m['reference_pbr_kind']='bare_metal';return m
chrome=polished('FineR4_polished_chrome',(.66,.68,.71),.105,.008);mirror=polished('FineR4_polished_mirror',(.92,.93,.95),.006,.001);mirror['realism_optical_role']='planar_mirror';hardware=[];garments=[]
for o in bpy.data.objects:
 if o.type not in ('MESH','CURVE'):continue
 for slot in o.material_slots:
  if slot.material and slot.material.name=='ir_chrome':slot.material=chrome
  elif slot.material and slot.material.name=='ir_mirror':slot.material=mirror
 key=o.get('program_key','')
 if o.type=='MESH' and '_native_garment_' in key:
  o.rotation_euler.z=.5+(int(key.rsplit('_',1)[1])%3-1)*.025;sub=o.modifiers.new('soft_native_cloth_boundaries','SUBSURF');sub.levels=1;sub.render_levels=1;garments.append(o.name)
  unit,tier,g=key.split('_')[0],key.split('_')[-2],key.split('_')[-1];parent=o.parent;yc=o.location.y;z=o.location.z+.055;angle=o.rotation_euler.z
  hanger=next(x for x in bpy.data.objects if x.get('program_key')==f'{unit}_hanger_{tier}_{g}')
  points=[]
  for x,zz in [(-.18,z-.13),(0,z-.055),(.18,z-.13),(-.18,z-.13)]:points.append((.28+math.cos(angle)*x,yc+math.sin(angle)*x,zz))
  for p,co in zip(hanger.data.splines[0].points,points):p.co=(*co,1)
 if o.type=='MESH' and key.endswith('_wc'):
  attribute=o.data.attributes.get('hardware');count=0
  if attribute and attribute.domain=='FACE':
   idx=len(o.data.materials);o.data.materials.append(chrome)
   for f,value in zip(o.data.polygons,attribute.data):
    if value.value>.5:f.material_index=idx;count+=1
  hardware.append({'object':o.name,'hardware_faces_chrome':count,'available_attributes':[a.name for a in o.data.attributes]})
plaster=bpy.data.materials.get('res03_plaster')
if plaster:changes.append(enrich(plaster,'paint'))
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(source.read_bytes()).hexdigest()==before
(ref/'realism_refinement_r28.json').write_text(json.dumps({'source':str(source),'source_sha256':before,'candidate':str(out),'changes':['Native draped shirt boundary subdivision and consistent hanger/garment orientation.','Mirror-specific almost-flat optical response and polished chrome instead of broad generic scan modulation.','Native WC hardware FACE attribute restored as distinct metal, preserving ceramic body.','Main plaster paint classified and assigned metre-based macro/meso/micro response.'],'plaster_change':changes,'garments':len(garments),'wc_hardware':hardware,'photorealism_accepted':False},indent=2));print(json.dumps({'saved':str(out),'garments':len(garments),'hardware_faces':[x['hardware_faces_chrome'] for x in hardware]}),flush=True)
