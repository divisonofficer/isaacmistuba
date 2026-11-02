"""Read-only assigned shader IOR inventory; flags inputs, never edits materials."""
import bpy,json,math,hashlib,argparse,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--blend',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []);assert not a.out.exists();bpy.ops.wm.open_mainfile(filepath=str(a.blend));used={}
for o in bpy.context.scene.objects:
 if o.hide_render or o.type not in ['MESH','CURVE','SURFACE','FONT','META']:continue
 for m in o.data.materials:
  if m:used.setdefault(m.name,[]).append(o.name)
rows=[];counts={'materials':len(used),'ior_shader_nodes':0,'linked_ior_inputs':0,'constant_ior_inputs':0}
def upstream(node,seen):
 if node in seen:return
 seen.add(node)
 for i in node.inputs:
  for l in i.links:upstream(l.from_node,seen)
for name,objects in used.items():
 m=bpy.data.materials[name]
 if not m.use_nodes:continue
 reachable=set()
 for n in m.node_tree.nodes:
  if n.type=='OUTPUT_MATERIAL' and n.is_active_output:
   for l in n.inputs['Surface'].links:upstream(l.from_node,reachable)
 def scan(tree,path,seen):
  if tree.as_pointer() in seen:return
  seen=seen|{tree.as_pointer()}
  for n in tree.nodes:
   if n.type=='GROUP' and n.node_tree:scan(n.node_tree,path+[n.name],seen)
   if n.type not in ['BSDF_PRINCIPLED','BSDF_GLASS','BSDF_REFRACTION'] or 'IOR' not in n.inputs:continue
   counts['ior_shader_nodes']+=1;s=n.inputs['IOR']
   if s.is_linked:counts['linked_ior_inputs']+=1;continue
   counts['constant_ior_inputs']+=1;v=float(s.default_value)
   if math.isfinite(v) and v>=1:continue
   bsdf_context={}
   for k in ['Metallic','Roughness','Transmission Weight']:
    if k in n.inputs:bsdf_context[k]={'linked':n.inputs[k].is_linked,'constant':float(n.inputs[k].default_value)}
   rows.append({'material':name,'node':n.name,'type':n.type,'group_path':path,'ior':v,'reason':'nonpositive_ior_constant' if v<=0 else 'subunit_or_nonfinite_ior_requires_context','active_surface_reachability':('reachable_in_root_tree' if n in reachable else 'not_reachable_in_root_tree') if not path else 'group_boundary_not_resolved','objects':objects,'shader_context':bsdf_context})
 scan(m.node_tree,[],set())
h=hashlib.sha256()
with a.blend.open('rb') as f:
 for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
a.out.write_text(json.dumps({'source':str(a.blend),'source_sha256':h.hexdigest(),'counts':counts,'findings':rows,'active_root_findings':sum(r['active_surface_reachability']=='reachable_in_root_tree' for r in rows),'scope':'Assigned materials on scene objects with hide_render false. Root material Surface upstream paths resolved; nested groups traversed but boundaries not resolved,collection inherited visibility not inferred. Constant socket checks only; linked IOR values not evaluated.','no_materials_edited':True,'photorealism_accepted':False,'limits':['An invalid or unusual input is evidence for shader contract review,not proof of its screen-space effect.','Do not mass-correct to a single IOR; separate dielectric/metal/coating roles and use actual rendered controls.']},indent=2)+'\n');print('IOR_AUDIT_COMPLETE',counts,'findings',len(rows),flush=True)
