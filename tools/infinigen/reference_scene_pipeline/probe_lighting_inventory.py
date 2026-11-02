"""Read-only current lighting evidence before another material/light change."""
import bpy,argparse,json,hashlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--blend',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bpy.ops.wm.open_mainfile(filepath=str(a.blend.resolve()));rows=[]
for o in bpy.context.scene.objects:
 if o.type!='LIGHT' or o.hide_render:continue
 d=o.data;rows.append({'object':o.name,'type':d.type,'energy':d.energy,'color':list(d.color),'location':list(o.matrix_world.translation),'rotation':list(o.matrix_world.to_euler()),'diffuse_factor':d.diffuse_factor,'specular_factor':d.specular_factor,'size':getattr(d,'size',None),'size_y':getattr(d,'size_y',None),'shape':getattr(d,'shape',None),'spread':getattr(d,'spread',None),'program_key':o.get('program_key')})
world=bpy.context.scene.world;wn=[]
if world and world.use_nodes:
 for n in world.node_tree.nodes:
  wn.append({'name':n.name,'type':n.type,'image':n.image.filepath if n.type=='TEX_ENVIRONMENT' and n.image else None,'inputs':{i.name:({'linked_from':i.links[0].from_node.name} if i.is_linked else str(i.default_value) if hasattr(i,'default_value') else None) for i in n.inputs}})
s=bpy.context.scene;a.out.write_text(json.dumps({'source':str(a.blend.resolve()),'source_sha256':hashlib.sha256(a.blend.read_bytes()).hexdigest(),'lights':rows,'world_nodes':wn,'view_transform':s.view_settings.view_transform,'exposure':s.view_settings.exposure,'gamma':s.view_settings.gamma,'scope':'Visible-by-object lights and root world nodes;collection visibility and radiometric contribution require render controls. Not a realism verdict.'},indent=2));print('LIGHT_INVENTORY',len(rows),a.out,flush=True)
