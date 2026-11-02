"""Preserve actual Movian geometry/native UV/maps; bounded authored honey finish trial."""
import bpy,json,hashlib
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/real_table_candidates';S=D/'review_studio.blend';O=D/'warm_elsa_studio.blend';assert not O.exists();sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();source_sha=sha(S);bpy.ops.wm.open_mainfile(filepath=str(S));objects=[o for o in bpy.context.scene.objects if o.type=='MESH' and o.get('original_asset_id')=='B07H8PNQXF'];assert objects;materials={m for o in objects for m in o.data.materials if m};copies={m:m.copy() for m in materials};rows=[]
for old,m in copies.items():
 m.name='Elsa_authored_honey_'+old.name;n,l=m.node_tree.nodes,m.node_tree.links;bs=next(x for x in n if x.type=='BSDF_PRINCIPLED');socket=bs.inputs['Base Color'];node=n.new('ShaderNodeMixRGB');node.name='Authored_honey_finish_gain';node.blend_type='MULTIPLY';node.inputs[0].default_value=1;node.inputs[2].default_value=(.75,.66,.50,1)
 if socket.is_linked:l.new(socket.links[0].from_socket,node.inputs[1])
 else:node.inputs[1].default_value=socket.default_value
 l.new(node.outputs[0],socket);bs.inputs['Coat Weight'].default_value=.15;bs.inputs['Coat Roughness'].default_value=.2;rows.append({'source_material':old.name,'material':m.name,'basecolor_gain':[.75,.66,.50],'authored_coat_weight':.15,'authored_coat_roughness':.2,'retained':'native4K colour/roughness/normal data and UV channels; no geometry orpose edits'})
for o in objects:
 for i,m in enumerate(o.data.materials):o.data.materials[i]=copies[m]
bpy.ops.wm.save_as_mainfile(filepath=str(O));assert sha(S)==source_sha;report={'source':str(S),'source_sha256':source_sha,'candidate':str(O),'candidate_sha256':sha(O),'objects':[o.name for o in objects],'materials':rows,'scope':'Authored optical finish only; original product mesh/UV andscene pose remain. Not native product finish ormeasuredBRDF;visual acceptance pending.'};(D/'warm_elsa_contract.json').write_text(json.dumps(report,indent=2));views=json.load(open(D/'review_views.json'));(D/'warm_elsa_views.json').write_text(json.dumps([v for v in views if v['name']=='B07H8PNQXF_view_a'],indent=2));print('WARM_ELSA_STUDIO_SAVED',flush=True)
