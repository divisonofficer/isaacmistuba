"""Actual captured city/park HDR environment trial, not a geometry substitute."""
import bpy,json,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[3];base=root/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r79.blend';out=base/'scene_candidate_r83.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();asset=root/'data/venue_refs/floor_plans_v3/environment_assets/greenwich_park_4k.hdr';provenance=json.loads(asset.with_name('greenwich_park_provenance.json').read_text());assert hashlib.sha256(asset.read_bytes()).hexdigest()==provenance['sha256'];bpy.ops.wm.open_mainfile(filepath=str(src));world=bpy.context.scene.world;assert world and world.use_nodes;tree=world.node_tree;outputs=[n for n in tree.nodes if n.type=='OUTPUT_WORLD' and n.is_active_output];assert len(outputs)==1;output=outputs[0]
def reachable(start):
 found=set();pending=[start]
 while pending:
  n=pending.pop()
  if n in found:continue
  found.add(n)
  for socket in n.inputs:
   pending.extend(link.from_node for link in socket.links)
 return found
backgrounds=[n for n in reachable(output) if n.type=='BACKGROUND'];assert len(backgrounds)==1,[(n.name,n.type) for n in backgrounds];bg=backgrounds[0];before={'color':list(bg.inputs['Color'].default_value),'strength':bg.inputs['Strength'].default_value,'linked_sources':[{'node':l.from_node.name,'socket':l.from_socket.name} for l in bg.inputs['Color'].links]};node=tree.nodes.new('ShaderNodeTexEnvironment');node.name='Captured_city_park_environment83';node.image=bpy.data.images.load(str(asset),check_existing=True);node.image.pack();node.projection='EQUIRECTANGULAR'
for link in list(bg.inputs['Color'].links):tree.links.remove(link)
tree.links.new(node.outputs['Color'],bg.inputs['Color']);assert node in reachable(output);assert bg in reachable(output);bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
(ref/'realism_refinement_r83.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'trigger':'Independent full reference review priorities1 real exterior replacing beige fog','change':'Only world Background Color input replaced by packed captured4k city/park HDR. Existing background strength,lights,geometry,materials,cameras andexposure untouched.','active_background_node':bg.name,'active_output_node':output.name,'environment_reachable_from_active_output':True,'previous_background':before,'environment_provenance':provenance,'photorealism_accepted':False,'limitations':['Captured panorama has no3D parallax or local building geometry','Not a Korean apartment skyline','Window/frame geometry still source79;curtainwall request remains open','Requires actual same-camera exterior exposure,glass andinterior regression review'],'requires':['breakout_kitchen','private_office','conference_reference_reverse']},indent=2)+'\n');print('Saved office83 captured environment trial',flush=True)
