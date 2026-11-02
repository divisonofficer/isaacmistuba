"""Bounded active wood shader inspection before choosing a colour/material trial."""
import bpy,json,hashlib
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';S=R/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r102.blend';O=D/'wood_r102_shader_profile.json';assert not O.exists();h=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();before=h(S);bpy.ops.wm.open_mainfile(filepath=str(S));rows=[]
for name in ['office02_reference_warm_oak','ir_cred_oak','ir_cred_oak2','BreakoutR41_UV_oak_veneer','office02_door_oak']:
 m=bpy.data.materials[name];bs=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED');up=set();pending=[link.from_node for link in bs.inputs['Base Color'].links]
 while pending:
  node=pending.pop()
  if node in up:continue
  up.add(node)
  pending.extend(link.from_node for socket in node.inputs for link in socket.links)
 nodes=[]
 for n in up:
  r={'name':n.name,'type':n.type,'inputs':{}}
  for socket in n.inputs:
   if socket.is_linked:r['inputs'][socket.name]={'from':[(x.from_node.name,x.from_socket.name) for x in socket.links]}
   elif hasattr(socket,'default_value'):
    value=socket.default_value
    try:json.dumps(value)
    except TypeError:value=list(value)
    r['inputs'][socket.name]=value
  if n.type=='TEX_IMAGE' and n.image:r['image']={'name':n.image.name,'filepath':n.image.filepath,'dimensions':list(n.image.size),'colorspace':n.image.colorspace_settings.name,'packed_sha256':hashlib.sha256(bytes(n.image.packed_file.data)).hexdigest() if n.image.packed_file else None}
  nodes.append(r)
 rows.append({'material':name,'basecolor_from':[(x.from_node.name,x.from_socket.name) for x in bs.inputs['Base Color'].links],'colour_upstream':nodes})
assert h(S)==before;O.write_text(json.dumps({'source':str(S),'source_sha256':before,'materials':rows,'scope':'Five specific active BaseColor shader paths,not full material/UV/physical or photographic verification.'},indent=2))
