"""Native glTF import with declared HSSD material profiles, never photo approval."""
import hashlib
from pathlib import Path
import bpy
ROOT=Path(__file__).resolve().parents[3]
def _sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _matching_materials(objects,key):
 return {m for o in objects if o.type=='MESH' for m in o.data.materials if m and (m.name==key or (m.name.startswith(key+'.') and m.name[len(key)+1:].isdigit()))}
def inspect_hssd_profile(objects,entry):
 errors=[];rows=[]
 for key,profile in entry.get('mr_override',{}).items():
  matches=_matching_materials(objects,key)
  if not matches:errors.append({'material':key,'reason':'declared_profile_not_assigned'});continue
  for m in matches:
   nodes=[n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED'] if m.use_nodes else []
   if len(nodes)!=1:errors.append({'material':m.name,'reason':'requires_single_native_principled'});continue
   bs=nodes[0];actual={}
   for name,field in [('Metallic','metallic'),('Roughness','roughness')]:
    s=bs.inputs[name];actual[name]=float(s.default_value)
    if s.is_linked or abs(s.default_value-profile[field])>1e-6:errors.append({'material':m.name,'reason':'declared_'+field+'_not_applied','actual':actual[name],'expected':profile[field],'linked':s.is_linked})
   ior=bs.inputs['IOR'];actual['IOR']=float(ior.default_value)
   if not ior.is_linked and ior.default_value<1:errors.append({'material':m.name,'reason':'invalid_constant_ior','actual':actual['IOR']})
   auxiliary={name:{'value':float(bs.inputs[name].default_value),'linked':bs.inputs[name].is_linked}
              for name in ['Coat Weight','Coat Roughness','Sheen Weight','Sheen Roughness','Specular IOR Level']}
   rows.append({'material':m.name,'declared_key':key,'actual':actual,
                'unvalidated_auxiliary_lobes':auxiliary})
 return {'asset_id':entry['id'],'rows':rows,'errors':errors,'pass':not errors,'scope':'Declared constant MR profiles and single native Principled IOR only;linked maps/complex shaders require manual integration. Profiles are inferred where index says inferred,not measured BRDF.'}
def apply_hssd_profile(objects,entry,*,repair_nonpositive_ior=None):
 profiles=entry.get('mr_override',{});targets={}
 for key,profile in profiles.items():
  matches=_matching_materials(objects,key);assert matches,('Missing declared material',key)
  for m in matches:
   nodes=[n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED'] if m.use_nodes else [];assert len(nodes)==1,('Complex material requires manual integration',m.name);bs=nodes[0]
   assert not bs.inputs['Metallic'].is_linked and not bs.inputs['Roughness'].is_linked,('Cannot replace linked data maps with constants',m.name)
   if not bs.inputs['IOR'].is_linked and bs.inputs['IOR'].default_value<1:assert repair_nonpositive_ior is not None and repair_nonpositive_ior>=1,('Explicit IOR repair policy required',m.name)
   targets[m]=(key,profile)
 # Isolate imported material instances from any unrelated objects sharing a datablock.
 copies={m:m.copy() for m in targets}
 for o in objects:
  if o.type!='MESH':continue
  for i,m in enumerate(o.data.materials):
   if m in copies:o.data.materials[i]=copies[m]
 changes=[]
 for old,m in copies.items():
  key,profile=targets[old];bs=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED');before={k:float(bs.inputs[k].default_value) for k in ['Metallic','Roughness','IOR']};bs.inputs['Metallic'].default_value=profile['metallic'];bs.inputs['Roughness'].default_value=profile['roughness']
  if not bs.inputs['IOR'].is_linked and bs.inputs['IOR'].default_value<1:bs.inputs['IOR'].default_value=repair_nonpositive_ior
  changes.append({'material':m.name,'source_material':old.name,'before':before,'after':{k:float(bs.inputs[k].default_value) for k in before},'profile':profile})
 result=inspect_hssd_profile(objects,entry);assert result['pass'],result;result['changes']=changes;return result
def inspect_and_repair_native_ior(objects,*,repair_nonpositive_ior=None):
 """Check every imported Principled, including assets without an MR override.

 Native files remain immutable. An explicit repair policy permits constant IOR<=0
 correction on isolated material copies; linked IOR remains unverified.
 """
 mats={m for o in objects if o.type=='MESH' for m in o.data.materials if m and m.use_nodes};copies={};changes=[];errors=[];rows=[]
 for m in mats:
  nodes=[n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED']
  for n in nodes:
   socket=n.inputs['IOR'];value=float(socket.default_value)
   if socket.is_linked:
    rows.append({'material':m.name,'node':n.name,'ior_linked':True,'validated':False});continue
   if value<=0 and repair_nonpositive_ior is not None:
    assert repair_nonpositive_ior>=1,'Explicit IOR policy must be >=1'
    if m not in copies:copies[m]=m.copy()
    copy=copies[m]
    copy.node_tree.nodes[n.name].inputs['IOR'].default_value=repair_nonpositive_ior
    changes.append({'source_material':m.name,'material':copy.name,'node':n.name,'ior_before':value,'ior_after':repair_nonpositive_ior,'policy':'explicit inferred constant repair, not measured'})
    value=repair_nonpositive_ior
   if value<1:errors.append({'material':m.name,'node':n.name,'reason':'invalid_constant_ior','ior':value})
   rows.append({'material':m.name,'node':n.name,'ior':value,'ior_linked':False,'validated':value>=1})
 for o in objects:
  if o.type=='MESH':
   for i,m in enumerate(o.data.materials):
    if m in copies:o.data.materials[i]=copies[m]
 return {'rows':rows,'changes':changes,'errors':errors,'pass':not errors,'scope':'Every imported Principled constant IOR; linked values and material classification/appearance unverified.'}

def import_curated_gltf(entry,*,repair_nonpositive_ior=None):
 path=Path(entry['path']);path=path if path.is_absolute() else ROOT/path
 expected=entry.get('copied_sha256',entry.get('source_sha256'));assert expected and _sha(path)==expected
 for dep in entry.get('verified_dependencies',[])+entry.get('copied_dependencies',[]):
  p=Path(dep['path']);p=p if p.is_absolute() else ROOT/p;assert _sha(p)==dep['sha256']
 for dep in entry.get('dependencies',[]):
  p=path.parent/dep['uri'];assert p.resolve().is_relative_to(path.parent.resolve());assert _sha(p)==dep['sha256']
 before=set(bpy.data.objects);bpy.ops.import_scene.gltf(filepath=str(path));bpy.context.view_layer.update();new=[o for o in bpy.data.objects if o not in before];objects=[o for o in new if o.type=='MESH'];assert objects
 profile=apply_hssd_profile(objects,entry,repair_nonpositive_ior=repair_nonpositive_ior) if entry.get('mr_override') else {'asset_id':entry['id'],'pass':True,'changes':[],'scope':'No declared external constant MR profile. Source shader still requires optical/visual review.'}
 native=inspect_and_repair_native_ior(objects,repair_nonpositive_ior=repair_nonpositive_ior)
 profile['native_ior_validation']=native;profile['pass']=profile['pass'] and native['pass']
 assert native['pass'],('Native material optical preflight failed',native['errors'])
 return new,objects,profile

def preserve_native_packed_image(image):
 """Keep embedded native bytes; repacking a blank-path embedded image can discard its packed data."""
 assert min(image.size)>0,('Undecoded native image',image.name)
 before=bytes(image.packed_file.data) if image.packed_file else None
 if before is None:image.pack()
 assert image.packed_file,('Native texture is not portable',image.name)
 after=bytes(image.packed_file.data)
 assert before is None or after==before,('Embedded native bytes changed',image.name)
 return {'name':image.name,'dimensions':list(image.size),'packed_sha256':hashlib.sha256(after).hexdigest(),'colorspace':image.colorspace_settings.name,'already_embedded':before is not None,'embedded_bytes_preserved':before is None or after==before}
