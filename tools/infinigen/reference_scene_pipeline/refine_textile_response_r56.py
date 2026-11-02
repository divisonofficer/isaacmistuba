"""Controlled chair textile reflectance trial; no geometry, colour or normal changes."""
import bpy,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
src=base/'scene_candidate_r53.blend';out=base/'scene_candidate_r56.blend'
assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest()
bpy.ops.wm.open_mainfile(filepath=str(src))
old=bpy.data.materials['BreakoutR30_fine_blue_upholstery'];m=old.copy();m.name='R56_textile_reflectance_trial'
n=m.node_tree.nodes;l=m.node_tree.links;bs=next(x for x in n if x.type=='BSDF_PRINCIPLED')
rough=bs.inputs['Roughness'].links[0].from_node;assert rough.type=='MAP_RANGE'
before={'roughness_range':[rough.inputs['To Min'].default_value,rough.inputs['To Max'].default_value],'specular':bs.inputs['Specular IOR Level'].default_value,'sheen':bs.inputs['Sheen Weight'].default_value}
rough.inputs['To Min'].default_value=.62;rough.inputs['To Max'].default_value=.86
bs.inputs['Specular IOR Level'].default_value=.40;bs.inputs['Sheen Weight'].default_value=.35
rows=[]
for o in bpy.data.objects:
 if not str(o.get('program_key','')).startswith('breakout_chair'):continue
 for slot in o.material_slots:
  if slot.material==old:slot.material=m;rows.append(o.name)
assert len(rows)>=8
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
(ref/'realism_refinement_r56.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'scope':'Chair textile BSDF response only; exact scan input,albedo,coordinates,normals,geometry,lights and exposure retained','before':before,'after':{'roughness_range':[.62,.86],'specular':.40,'sheen':.35},'objects':rows,'photorealism_accepted':False,'requires':'Paired actual close and wide renders;reject plastic/glossy appearance or exaggerated surface grain'},indent=2))
print('SAVED',out,flush=True)
