"""Read-only used image dependency preflight; packed/existing repository images are portable in scope."""
import bpy,argparse,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];p=argparse.ArgumentParser();p.add_argument('--blend',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bpy.ops.wm.open_mainfile(filepath=str(a.blend.resolve()));seen_trees=set();seen_objects=set();images={};materials=set()
def tree(nt,reason):
 if not nt or nt.as_pointer() in seen_trees:return
 seen_trees.add(nt.as_pointer())
 for node in nt.nodes:
  image=getattr(node,'image',None)
  if image:images.setdefault(image.as_pointer(),{'image':image,'used_by':[]})['used_by'].append(reason+'/'+node.name)
  child=getattr(node,'node_tree',None)
  if child:tree(child,reason+'/'+node.name)
  for inp in node.inputs:
   if inp.is_linked or not hasattr(inp,'default_value'):continue
   value=inp.default_value
   if isinstance(value,bpy.types.Material):mat(value)
   elif isinstance(value,bpy.types.Object):obj(value)
   elif isinstance(value,bpy.types.Collection):
    for target in value.all_objects:obj(target)
def mat(m):
 if m:materials.add(m.name);tree(m.node_tree,'material:'+m.name)
def obj(o):
 if o.as_pointer() in seen_objects:return
 seen_objects.add(o.as_pointer())
 for slot in o.material_slots:mat(slot.material)
 for mod in o.modifiers:
  if getattr(mod,'show_render',False):tree(getattr(mod,'node_group',None),'modifier:'+o.name+'/'+mod.name)
 if o.instance_collection:
  for target in o.instance_collection.all_objects:obj(target)
for o in bpy.context.scene.objects:
 if not o.hide_render:obj(o)
if bpy.context.scene.world:tree(bpy.context.scene.world.node_tree,'world')
rows=[];errors=[]
for item in images.values():
 im=item['image'];packed=bool(im.packed_file or len(im.packed_files));path=Path(bpy.path.abspath(im.filepath,library=im.library)).resolve() if im.filepath else None;generated=im.source in ['GENERATED','VIEWER'];inside=bool(path and path.is_relative_to(ROOT));exists=bool(path and path.exists());status='packed' if packed else 'generated' if generated else 'repository_file' if inside and exists else 'outside_repository_unpacked' if exists else 'missing_unpacked_file';row={'image':im.name,'source':im.source,'filepath':str(path) if path else None,'status':status,'used_by':item['used_by']};rows.append(row)
 if status not in ['packed','generated','repository_file']:errors.append(row)
a.out.write_text(json.dumps({'source':str(a.blend.resolve()),'source_sha256':hashlib.sha256(a.blend.read_bytes()).hexdigest(),'status':'pass_used_image_dependency_scope' if not errors else 'image_dependency_repair_required','objects_visited':len(seen_objects),'material_count':len(materials),'image_count':len(rows),'images':rows,'errors':errors,'scope':'Scene objects not explicitly hide_render,material/world nodes,nested groups,unlinked material/object/collection sockets and enabled geometry-node modifiers. Conservative for collection visibility;does not certify arbitrary scripted runtime asset loading,font or non-image dependencies.','photorealism_accepted':False},indent=2));print(json.dumps({'image_count':len(rows),'errors':len(errors),'out':str(a.out)}),flush=True)
