"""Yaw-only followup to89's failed solar-backdrop sanity check; no room RGB yet."""
import hashlib
import json
import math
from pathlib import Path
import bpy
import numpy as np

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
REF=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
SOURCE,OUTPUT=BASE/'scene_candidate_r89.blend',BASE/'scene_candidate_r90.blend'
STAGE=REF/'urban_environment_r90_controls'
assert not OUTPUT.exists() and not STAGE.exists()
STAGE.mkdir()
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
before=sha(SOURCE)
previous=json.loads((REF/'realism_refinement_r89.json').read_text())
cal=json.loads((REF/'urban_environment_r89_calibration/results.json').read_text())
bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
main=bpy.context.scene
world=main.world
tree=world.node_tree
env=next(n for n in tree.nodes if n.type=='TEX_ENVIRONMENT')
assert not env.inputs['Vector'].is_linked
coord=tree.nodes.new('ShaderNodeTexCoord')
rotate=tree.nodes.new('ShaderNodeVectorRotate')
rotate.name='R90_verified_sky_at_solar_direction'
rotate.rotation_type='AXIS_ANGLE'
rotate.inputs['Axis'].default_value=(0,0,1)
rotate.inputs['Angle'].default_value=math.radians(270)
tree.links.new(coord.outputs['Generated'],rotate.inputs['Vector'])
tree.links.new(rotate.outputs['Vector'],env.inputs['Vector'])
world.name='R90_urban_HDR_yaw270'
sun=main.objects[previous['replacement_sun']]
probe=bpy.data.scenes.new('R90_horizontal_card_check')
probe.world=world
probe.render.engine='CYCLES'
probe.cycles.device='CPU'
probe.cycles.samples=2048
probe.cycles.seed=47
probe.cycles.use_denoising=False
probe.render.threads_mode='FIXED'
probe.render.threads=4
probe.render.resolution_x=probe.render.resolution_y=16
probe.render.resolution_percentage=100
probe.render.image_settings.file_format='OPEN_EXR'
probe.render.image_settings.color_depth='32'
probe.view_settings.exposure=0
mesh=bpy.data.meshes.new('R90_diagnostic_card_not_saved')
mesh.from_pydata([(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0)],[],[(0,1,2,3)])
card=bpy.data.objects.new(mesh.name,mesh)
probe.collection.objects.link(card)
material=bpy.data.materials.new('R90_diagnostic_Lambert018')
material.use_nodes=True
material.node_tree.nodes.clear()
diffuse=material.node_tree.nodes.new('ShaderNodeBsdfDiffuse')
diffuse.inputs['Color'].default_value=(.18,.18,.18,1)
out=material.node_tree.nodes.new('ShaderNodeOutputMaterial')
material.node_tree.links.new(diffuse.outputs[0],out.inputs['Surface'])
mesh.materials.append(material)
camera_data=bpy.data.cameras.new('R90_diagnostic_camera_not_saved')
camera=bpy.data.objects.new(camera_data.name,camera_data)
probe.collection.objects.link(camera)
camera.location=(0,0,1)
camera_data.type='ORTHO'
camera_data.ortho_scale=.2
probe.camera=camera
light=sun.copy()
light.data=sun.data.copy()
probe.collection.objects.link(light)
rows=[]
for name,visible in [('ambient_only',False),('ambient_and_replacement_solar',True)]:
    light.hide_render=not visible
    path=STAGE/(name+'.exr')
    probe.render.filepath=str(path)
    bpy.ops.render.render(write_still=True,scene=probe.name)
    image=bpy.data.images.load(str(path),check_existing=False)
    values=np.empty(len(image.pixels),dtype=np.float32)
    image.pixels.foreach_get(values)
    channels=len(values)//256
    rgb=values.reshape(16,16,channels)[4:12,4:12,:3].mean(axis=(0,1))
    bpy.data.images.remove(image)
    rows.append({'case':name,'file':str(path),'sha256':sha(path),'mean_linear_RGB':rgb.tolist(),
                 'mean_linear_Y':float(rgb@np.array([.2126,.7152,.0722]))})
old={r['case']:r['mean_linear_Y'] for r in cal['rows']}
ambient_ratio=rows[0]['mean_linear_Y']/old['A_reference_diffuse_sky']
total_ratio=rows[1]['mean_linear_Y']/old['B_reference_sky_with_solar_disc']
solar_ratio=(rows[1]['mean_linear_Y']-rows[0]['mean_linear_Y'])/(old['B_reference_sky_with_solar_disc']-old['A_reference_diffuse_sky'])
assert abs(ambient_ratio-1)<.04 and abs(total_ratio-1)<.05 and abs(solar_ratio-1)<.12,(ambient_ratio,total_ratio,solar_ratio)
results={'source':str(SOURCE),'source_sha256':before,'rows':rows,'yaw_degrees':270,
         'ambient_ratio_vs_original88':ambient_ratio,'total_ratio_vs_original88':total_ratio,
         'solar_difference_ratio_vs_original88':solar_ratio,
         'solar_backdrop_selection':'Source89 empty-world actualsolar-direction renders:0/180/210 showbuilding atcenter;270 showsclearsky aroundsolar direction. Source90 finalsame-world confirmation required.',
         'scope':'Horizontalgraycard transfer only;not room/reference/photo pass. Existing89 replacementSun energy/colour/direction andallgeometry preserved. No horizon pitch/exposure change.'}
(STAGE/'results.json').write_text(json.dumps(results,indent=2)+'\n')
for obj in [light,card,camera]:bpy.data.objects.remove(obj,do_unlink=True)
bpy.data.scenes.remove(probe)
assert sha(SOURCE)==before
bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT))
metadata={**previous,'source':str(SOURCE),'source_sha256':before,'candidate':str(OUTPUT),
          'candidate_sha256':sha(OUTPUT),'baseline_retained_revision':88,'environment_yaw':math.radians(270),
          'yaw_control':str(STAGE/'results.json'),'yaw_control_sha256':sha(STAGE/'results.json'),
          'change':'89 hybridHDR+measuredSun retained;horizontalHDRyaw270 only correctssolar directionbackdrop. Raw89 heldbefore roomRGB becauseSun-facingbackdrop wasopaque building.',
          'photorealism_accepted':False,'retained_revision':88}
(REF/'realism_refinement_r90.json').write_text(json.dumps(metadata,indent=2)+'\n')
print('URBAN_ENVIRONMENT_R90_SAVED',flush=True)
