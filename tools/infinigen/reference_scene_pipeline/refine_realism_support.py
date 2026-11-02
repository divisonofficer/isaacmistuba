"""Measured contact and new-metal normal corrections before paired rendering."""
import argparse,bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
from material_detail import noise,bump
ROOT=Path(__file__).resolve().parents[3];p=argparse.ArgumentParser();p.add_argument('--scene',choices=['office','residential'],required=True);a=p.parse_args();office=a.scene=='office';scene='commercial_office_floor_02' if office else 'dual_unit_residential_floor_03';seed=48712502 if office else 48712503;old=19 if office else 23;rev=20 if office else 24;base=ROOT/'out/infinigen_v2'/f'kr_{scene}_{seed}/full';ref=ROOT/'data/venue_refs/floor_plans_v3'/scene;source=base/f'scene_candidate_r{old}.blend';out=base/f'scene_candidate_r{rev}.blend';assert not out.exists();before=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source));fixes=[]
if office:
 top=max(max((o.matrix_world@Vector(c)).z for c in o.bound_box) for o in bpy.data.objects if o.get('program_key')=='coffee_worktop');body=next(o for o in bpy.data.objects if o.get('program_key')=='coffee_machine');low=min((body.matrix_world@Vector(c)).z for c in body.bound_box);mat=bpy.data.materials['FineR1_rubber_controls']
 for x in (body.location.x-.04,body.location.x+.04):
  for y in (body.location.y-.14,body.location.y+.14):
   z0=top+.0003;z1=low+.0002;assert z1>z0;bpy.ops.mesh.primitive_cube_add(size=1,location=(x,y,(z0+z1)/2));o=bpy.context.object;o.name='FineR1_machine_rubber_foot';o.dimensions=(.018,.018,z1-z0);bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(mat);o['reference_scene_owner']=scene;o['program_key']='machine_rubber_foot';o['audit_kind']='fixture'
 for o in bpy.data.objects:
  if o.get('program_key') in ('coffee_machine_carafe','machine_pitcher_handle'):o.location.z-=.003
 fixes.append({'support':'four actual rubber feet under case; pitcher contacts drip tray','case_bottom_z':low,'worktop_top_z':top})
else:
 for o in bpy.data.objects:
  if o.get('program_key','').endswith('_folded_knit'):
   # Original native shelf is 25mm thick: support top is shelf centre +12.5mm.
   o.location.z+=.0105
 fixes.append({'folded_knit_support':'Corrected shelf top offset by10.5mm, leaving0.5mm clearance instead of1cm penetration.'})
for m in bpy.data.materials:
 if not m.name.startswith('FineR1_') or m.get('reference_pbr_kind')!='bare_metal':continue
 n=m.node_tree.nodes;l=m.node_tree.links;bs=next(x for x in n if x.type=='BSDF_PRINCIPLED')
 if not bs.inputs['Normal'].is_linked:
  geo=n.new('ShaderNodeNewGeometry');height=noise(n,l,geo.outputs['Position'],1100,(.04,1,.04));l.new(bump(n,l,height,.000009,.2),bs.inputs['Normal']);fixes.append({'metal_normal_added':m.name,'distance_m':.000009})
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(source.read_bytes()).hexdigest()==before;(ref/f'realism_refinement_r{rev}.json').write_text(json.dumps({'source':str(source),'source_sha256':before,'candidate':str(out),'fixes':fixes,'visual_realism_accepted':False,'paired_render_pending':True},indent=2));print(json.dumps({'saved':str(out),'fixes':fixes}),flush=True)
