"""Audit every assigned renderable material, including untagged native shaders and curves."""
import argparse,bpy,json,hashlib,collections
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--blend',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bpy.ops.wm.open_mainfile(filepath=str(a.blend.resolve()));used=collections.defaultdict(list)
for o in bpy.data.objects:
 if o.type not in ('MESH','CURVE','SURFACE','FONT','META') or o.hide_render:continue
 for m in o.data.materials:
  if m:used[m.name].append(o.name)
rows=[]
for name,objects in used.items():
 m=bpy.data.materials[name];bs=next((n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None) if m.use_nodes else None;warnings=[];notes=[];kind=m.get('reference_pbr_kind');emission=False
 if bs:
  emission=not bs.inputs['Emission Strength'].is_linked and bs.inputs['Emission Strength'].default_value>1
  metal=bs.inputs['Metallic'];rough=bs.inputs['Roughness'];spec=bs.inputs['Specular IOR Level']
  if not metal.is_linked and .02<metal.default_value<.98:warnings.append('constant_intermediate_metallic_requires_layering_or_coating_review')
  if not spec.is_linked and spec.default_value<.05 and not emission:notes.append('suppressed_specular_requires_material_context')
  for channel in ('Roughness','Normal'):
   if not bs.inputs[channel].is_linked and not emission:notes.append('constant_'+channel.lower()+'_review_amplitude_and_context')
  if kind in ('paint','wood','textile','carpet','glazed_ceramic','stone','tile','grout','glass') and not metal.is_linked and metal.default_value!=0:warnings.append('identified_dielectric_is_metallic')
  if kind=='bare_metal' and not metal.is_linked and metal.default_value!=1:warnings.append('identified_bare_metal_not_metallic1')
  if bs.inputs['Transmission Weight'].default_value>.5 and not 1.25<=bs.inputs['IOR'].default_value<=1.8:warnings.append('glass_like_ior_requires_review')
 else:notes.append('shader_group_or_nonprincipled_manual_review')
 for n in m.node_tree.nodes if m.use_nodes else []:
  if n.type=='TEX_IMAGE' and n.image:
   filename=n.image.filepath.lower()
   if any(s in filename for s in ('normal','roughness','displacement')) and n.image.colorspace_settings.name=='sRGB':warnings.append('data_texture_is_srgb:'+n.image.name)
 rows.append({'material':name,'kind':kind,'objects':objects,'emissive_exception':emission,'warnings':warnings,'context_notes':notes,'status':'parameter_warning' if warnings else 'needs_context' if notes else 'bounded_parameter_checks_clear'})
result={'source':str(a.blend.resolve()),'source_sha256':hashlib.sha256(a.blend.read_bytes()).hexdigest(),'assigned_material_count':len(rows),'all_assigned_materials_in_scope':True,'status_counts':dict(collections.Counter(r['status'] for r in rows)),'materials':rows,'warnings':[{'material':r['material'],'warnings':r['warnings']} for r in rows if r['warnings']],'photorealism_accepted':False,'limitations':['Valid parameters and linked maps are not proof of visual realism.','Context notes require rendered inspection, especially polished surfaces, emitters, leaf shaders and fabric.','Node-group internals are not inferred as flat shaders; they remain explicit manual-review entries.']};a.out.write_text(json.dumps(result,indent=2));print(json.dumps({'materials':len(rows),'statuses':result['status_counts'],'warnings':result['warnings']}),flush=True)
