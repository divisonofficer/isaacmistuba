"""Correct root image BOX projection only when its complete known coordinate ancestry is explicit UV."""
import bpy,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r42.blend';out=base/'scene_candidate_r43.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src))
def origins(socket,seen=None):
 seen=set() if seen is None else set(seen)
 if not socket.is_linked:return set()
 result=set()
 for link in socket.links:
  node=link.from_node;key=(node.as_pointer(),link.from_socket.identifier)
  if key in seen:result.add('unknown_cycle');continue
  visited=seen|{key}
  if node.type=='TEX_COORD':result.add('UV' if link.from_socket.name=='UV' else 'other_coordinate')
  elif node.type=='UVMAP':result.add('UV')
  elif node.type in ['VECT_MATH','MAPPING','REROUTE','SEPXYZ','COMBXYZ']:
   for inp in node.inputs:
    if inp.is_linked:result|=origins(inp,visited)
  else:result.add('unknown_node_'+node.type)
 return result
owned=[o for o in bpy.data.objects if o.get('reference_scene_owner')=='commercial_office_floor_02'];mats={m for o in owned for m in [s.material for s in o.material_slots] if m and m.use_nodes};changes=[];checked=0
for old in sorted(mats,key=lambda m:m.name):
 bad=[]
 for n in old.node_tree.nodes:
  if n.type=='TEX_IMAGE':
   checked+=1
   if n.projection=='BOX' and origins(n.inputs['Vector'])=={'UV'}:bad.append(n.name)
 if not bad:continue
 new=old.copy();new.name='R43_UV_'+old.name
 for name in bad:
  node=new.node_tree.nodes[name];node.projection='FLAT';changes.append({'material_before':old.name,'material_after':new.name,'image':node.image.name if node.image else None,'node':name,'coordinate_ancestry':['UV'],'old_projection':'BOX','new_projection':'FLAT'})
 for o in owned:
  for slot in o.material_slots:
   if slot.material==old:slot.material=new
assert changes;assert any('oak_legs' in c['material_before'] for c in changes)
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r43.json').write_text(json.dumps({'source':str(src),'candidate':str(out),'source_sha256':sha,'trigger':'Cabinet UV/BOX failure can also affect chair-leg scan material. Follow actual coordinate links,not material names,for bounded correction.','root_images_checked':checked,'changes':changes,'scope':'root image nodes on owned-object material assignments;recursive node groups/unknown coordinate sources not corrected or certified. Geometry,lighting,exposure unchanged.','photorealism_accepted':False,'requires':'same-camera leg and cabinetry regression render'},indent=2));print('SAVED',out,'image fixes',len(changes),flush=True)
