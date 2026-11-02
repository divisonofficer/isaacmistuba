"""Actual assigned shader-channel audit; explicitly not a visual quality verdict."""
import argparse,hashlib,json,sys
from pathlib import Path
import bpy
p=argparse.ArgumentParser();p.add_argument('--blend',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]);bpy.ops.wm.open_mainfile(filepath=str(a.blend.resolve()))
usage={}
for o in bpy.data.objects:
 if o.type in ('MESH','CURVE','SURFACE','FONT','META'):
  for slot in o.material_slots:
   if slot.material:usage.setdefault(slot.material.name,[]).append(o.name)
records=[];errors=[]
for name,objects in usage.items():
 m=bpy.data.materials[name];kind=m.get('reference_pbr_kind')
 if kind is None:
  if name.startswith(('ir_sec_fabric','ir_sec_cushion','ir_sec_pillow','ir_wdc_fabric','ir_bal_teal','ir_sfb_white','ir_sfb_cream','ir_sfb_throw','ir_sfb_oat','ir_sfb_greige','ir_sfb_petrol')):kind='textile'
  elif name.startswith(('ir_sdt_stone','ir_sct_stone','ir_kit_top')):kind='stone'
  elif name.startswith(('office02_reference_warm_oak','office02_reception_oak')):kind='wood'
 if kind is None and (m.get('tile_floor') or name.startswith('ir_wall_tile_')):kind='tile'
 if kind is None:continue
 bs=next((x for x in m.node_tree.nodes if x.type=='BSDF_PRINCIPLED'),None) if m.use_nodes else None
 if bs is None:errors.append({'material':name,'reason':'no_principled_surface'});continue
 links={channel:bool(bs.inputs[channel].links) for channel in ['Base Color','Roughness','Normal','Metallic']}
 metallic=bs.inputs['Metallic'].default_value
 if kind in ('textile','carpet','wood','paint','stone','floor_stone','bare_metal','glazed_ceramic','glass','tile','grout'):
  for channel in ('Roughness','Normal'):
   if not links[channel]:errors.append({'material':name,'reason':'missing_linked_'+channel.lower()})
 if kind in ('textile','carpet','wood','paint','stone','floor_stone','glazed_ceramic','glass','tile','grout') and (links['Metallic'] or metallic!=0):errors.append({'material':name,'reason':'dielectric_metallic_not_zero'})
 if kind=='bare_metal' and (links['Metallic'] or metallic!=1):errors.append({'material':name,'reason':'bare_metal_metallic_not_one'})
 records.append({'material':name,'kind':kind,'assigned_objects':objects,'linked_channels':links,'metallic':metallic})
# Role coverage prevents a name typo silently omitting a whole furniture family.
by_object={}
for row in records:
 for name in row['assigned_objects']:by_object.setdefault(name,set()).add(row['kind'])
role_coverage=[]
for o in bpy.data.objects:
 key=o.get('program_key','')
 if o.type!='MESH' or o.get('reference_scene_owner')!='dual_unit_residential_floor_03':continue
 if not any(token in key for token in ('living_sectional','dining_chair_','balcony_chair_','master_bed','bedroom2_bed','bedroom3_bed')):continue
 if key.endswith('_draped_duvet'):continue
 good='textile' in by_object.get(o.name,set());role_coverage.append({'object':o.name,'role':key,'textile_material_detected':good})
 if not good:errors.append({'object':o.name,'reason':'required_upholstery_role_not_covered'})
for o in bpy.data.objects:
 if o.type!='MESH' or not o.get('reference_scene_owner'):continue
 key=o.get('program_key','')
 expected={'glazed_ceramic'} if key.endswith('_wc') else {'glass','bare_metal'} if key.endswith('_shower') else {'glazed_ceramic'} if key.endswith('_vanity') else set()
 if not expected:continue
 actual=by_object.get(o.name,set())
 if not expected.issubset(actual):errors.append({'object':o.name,'reason':'required_finish_family_missing','expected':sorted(expected),'detected':sorted(actual)})
result={'source':str(a.blend.resolve()),'source_sha256':hashlib.sha256(a.blend.read_bytes()).hexdigest(),'status':'pass_bounded_shader_contract' if not errors else 'material_contract_failed','checked_assigned_materials':len(records),'records':records,'role_coverage':role_coverage,'errors':errors,'limitations':['Only identified PBR material families checked; unknown materials not certified.','Linked nodes and correct metallic values do not establish visible realism. Paired direct visual checks are required.'],'visual_acceptance':False};a.out.write_text(json.dumps(result,indent=2));print(json.dumps({k:result[k] for k in ('status','checked_assigned_materials','errors')}))
