"""Saved-world surface reachability gate; catches inactive-node HDR edits before RGB."""
import bpy,argparse,json,hashlib
from pathlib import Path

def audit(blend,expected_image):
 blend=Path(blend).resolve();expected_image=Path(expected_image).resolve();bpy.ops.wm.open_mainfile(filepath=str(blend));world=bpy.context.scene.world;errors=[];rows=[]
 if not world or not world.use_nodes:errors.append('No node-based world')
 else:
  tree=world.node_tree;outputs=[n for n in tree.nodes if n.type=='OUTPUT_WORLD' and n.is_active_output]
  if not outputs:errors.append('No active World Output')
  for output in outputs:
   found=set();pending=[l.from_node for l in output.inputs['Surface'].links]
   while pending:
    node=pending.pop()
    if node in found:continue
    found.add(node)
    for socket in node.inputs:pending.extend(l.from_node for l in socket.links)
   environments=[n for n in found if n.type=='TEX_ENVIRONMENT'];envrows=[]
   for node in environments:
    image=node.image;packed=bool(image and image.packed_file);digest=hashlib.sha256(image.packed_file.data).hexdigest() if packed else None
    envrows.append({'node':node.name,'image':image.name if image else None,'dimensions':list(image.size) if image else None,'packed':packed,'packed_sha256':digest,'expected_sha256_match':digest==hashlib.sha256(expected_image.read_bytes()).hexdigest()})
   valid=any(x['expected_sha256_match'] and x['dimensions'][0]>0 and x['dimensions'][1]>0 for x in envrows)
   row={'output':output.name,'target':output.target,'surface_upstream_nodes':[n.name for n in found],'environments':envrows,'expected_environment_reachable':valid};rows.append(row)
   if not valid:errors.append({'output':output.name,'reason':'Expected packed HDR absent from active world Surface path'})
 return {'source':str(blend),'source_sha256':hashlib.sha256(blend.read_bytes()).hexdigest(),'expected_image':str(expected_image),'expected_image_sha256':hashlib.sha256(expected_image.read_bytes()).hexdigest(),'auditor_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'outputs':rows,'errors':errors,'pass':not errors,'photorealism_accepted':False,'scope':'Actual saved world Surface graph reachability and packed-image identity only. Does not prove rays reach environment through windows,proper exposure,correct city/region,3D parallax orphotorealism.'}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--blend',type=Path,required=True);p.add_argument('--expected-image',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();d=audit(a.blend,a.expected_image);a.out.write_text(json.dumps(d,indent=2)+'\n');print(json.dumps({'pass':d['pass'],'errors':d['errors']}));raise SystemExit(bool(d['errors']))
