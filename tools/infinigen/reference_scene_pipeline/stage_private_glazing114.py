import bpy,json,sys
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];D=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/native_private_glazing114';assert not (D/'studio.blend').exists();bpy.ops.wm.open_mainfile(filepath=str(D/'asset.blend'))
s=bpy.context.scene;w=bpy.data.worlds.new('Pilot actual urban HDR');w.use_nodes=True;s.world=w;bg=w.node_tree.nodes['Background'];bg.inputs['Strength'].default_value=.35;e=w.node_tree.nodes.new('ShaderNodeTexEnvironment');e.image=bpy.data.images.load(str(ROOT/'data/venue_refs/floor_plans_v3/environment_assets/urban_courtyard_02_4k.hdr'));e.image.pack();w.node_tree.links.new(e.outputs['Color'],bg.inputs['Color'])
for name,loc,power,size in [('Studio_Key',(1,-3,4),500,3),('Studio_Edge',(-3,1,3),400,2)]:
 d=bpy.data.lights.new(name,'AREA');d.energy=power;d.shape='DISK';d.size=size;o=bpy.data.objects.new(name,d);s.collection.objects.link(o);o.location=loc;o.rotation_euler=(Vector((0,0,1.3))-o.location).to_track_quat('-Z','Y').to_euler()
s.view_settings.view_transform='AgX';s.view_settings.exposure=0
bpy.ops.wm.save_as_mainfile(filepath=str(D/'studio.blend'))
(D/'views.json').write_text(json.dumps([{'name':'native_fullheight_glazing','location':[3.4,-5.5,2.8],'target':[0,0,1.3],'hfov':51,'render_width':768,'samples':32}],indent=2)+'\n');print('STUDIO_READY',flush=True)
