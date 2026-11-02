import bpy,json,math
from pathlib import Path
from mathutils import Vector
r=Path('/jarvis/project/robomituba');ref=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r89.blend';d=json.loads((ref/'urban_environment_r89_calibration/results.json').read_text());out=ref/'urban_environment_r89_calibration/yaw_diagnostics';assert not out.exists();out.mkdir();bpy.ops.wm.read_factory_settings(use_empty=True)
with bpy.data.libraries.load(str(src),link=False) as (a,b):b.worlds=['R89_urban_HDR_measured_solar_replacement']
s=bpy.context.scene;s.world=b.worlds[0];data=bpy.data.cameras.new('Probe');o=bpy.data.objects.new('Probe',data);s.collection.objects.link(o);s.camera=o;o.rotation_euler=Vector(d['solar_direction_world']).to_track_quat('-Z','Y').to_euler();data.angle=math.radians(25);s.render.engine='CYCLES';s.cycles.device='CPU';s.cycles.samples=1;s.render.resolution_x=s.render.resolution_y=512;s.render.resolution_percentage=100;s.render.threads_mode='FIXED';s.render.threads=4;s.view_settings.view_transform='AgX';s.view_settings.exposure=0;s.render.use_persistent_data=True;tree=s.world.node_tree;env=next(n for n in tree.nodes if n.type=='TEX_ENVIRONMENT');coord=tree.nodes.new('ShaderNodeTexCoord');rotate=tree.nodes.new('ShaderNodeVectorRotate');rotate.rotation_type='AXIS_ANGLE';rotate.inputs['Axis'].default_value=(0,0,1);tree.links.new(coord.outputs['Generated'],rotate.inputs['Vector']);tree.links.new(rotate.outputs['Vector'],env.inputs['Vector'])
for yaw in [90,180,210,270]:
 rotate.inputs['Angle'].default_value=math.radians(yaw);s.render.filepath=str(out/f'solar_backdrop_yaw{yaw}.png');bpy.ops.render.render(write_still=True)
print('SUN_FACING_YAW_CONTROLS_COMPLETE',flush=True)
