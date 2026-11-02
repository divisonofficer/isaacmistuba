"""Installed-room HDR trial after asset-only hold; all rays, no extra Sun."""
import bpy, json, hashlib, math, numpy as np
from pathlib import Path
R=Path(__file__).resolve().parents[3]
D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
B=R/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
source,out=B/'scene_candidate_r98.blend',B/'scene_candidate_r99.blend'
assert not out.exists()
assert json.loads((D/'breakout_r98_north_fullheight_glazing/visual_review.json').read_text())['retain_bounded_glazing_change']
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
source_sha=sha(source)
pre=json.loads((D/'canary_world_preflight/results.json').read_text())
assert sha(pre['world_asset'])==pre['world_asset_sha256']
bpy.ops.wm.open_mainfile(filepath=str(source))
main=bpy.context.scene
original=main.world
assert not any(o.type=='LIGHT' and o.data.type=='SUN' for o in main.objects)
with bpy.data.libraries.load(pre['world_asset'],link=False) as (src,dst):
    dst.worlds=[pre['world_name']]
world=dst.worlds[0]
world.node_tree.nodes['CanaryWorldYaw'].inputs['Angle'].default_value=math.pi/2
# Measure the CURRENT procedural source and the rotated captured world separately.
stage=D/'captured_world_r99_probe';assert not stage.exists();stage.mkdir()
probe=bpy.data.scenes.new('R99_Independent_Lambert_Probe')
probe.render.engine='CYCLES';probe.cycles.device='CPU';probe.cycles.samples=2048
probe.cycles.seed=47;probe.cycles.use_denoising=False
probe.render.threads_mode='FIXED';probe.render.threads=2
probe.render.resolution_x=probe.render.resolution_y=16
probe.render.resolution_percentage=100
probe.render.image_settings.file_format='OPEN_EXR';probe.render.image_settings.color_depth='32'
mesh=bpy.data.meshes.new('R99_ProbeCard')
mesh.from_pydata([(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0)],[],[(0,1,2,3)])
card=bpy.data.objects.new(mesh.name,mesh);probe.collection.objects.link(card)
mat=bpy.data.materials.new('R99_ProbeLambert018');mat.use_nodes=True;mat.node_tree.nodes.clear()
diff=mat.node_tree.nodes.new('ShaderNodeBsdfDiffuse');diff.inputs['Color'].default_value=(.18,.18,.18,1)
output=mat.node_tree.nodes.new('ShaderNodeOutputMaterial');mat.node_tree.links.new(diff.outputs[0],output.inputs['Surface'])
mesh.materials.append(mat)
camera_data=bpy.data.cameras.new('R99_ProbeCamera');camera=bpy.data.objects.new(camera_data.name,camera_data)
probe.collection.objects.link(camera);camera.location=(0,0,1)
camera_data.type='ORTHO';camera_data.ortho_scale=.2;probe.camera=camera
measurements=[]
for label,w in [('original_current_world',original),('captured_yaw90_world',world)]:
    probe.world=w;file=stage/(label+'.exr');probe.render.filepath=str(file)
    bpy.ops.render.render(write_still=True,scene=probe.name)
    image=bpy.data.images.load(str(file),check_existing=False)
    pixels=np.empty(len(image.pixels),np.float32);image.pixels.foreach_get(pixels)
    rgb=pixels.reshape(16,16,-1)[4:12,4:12,:3].mean(axis=(0,1))
    measurements.append({'case':label,'mean_linear_RGB':rgb.tolist(),
                         'mean_linear_Y':float(rgb@np.array([.2126,.7152,.0722])),
                         'path':str(file),'sha256':sha(file)})
    bpy.data.images.remove(image)
ratio=measurements[1]['mean_linear_Y']/measurements[0]['mean_linear_Y']
assert abs(ratio-1)<.03,ratio
for obj in [card,camera]:bpy.data.objects.remove(obj,do_unlink=True)
bpy.data.scenes.remove(probe)
main.world=world
assert sha(source)==source_sha
bpy.ops.wm.save_as_mainfile(filepath=str(out))
meta=json.loads((D/'realism_refinement_r98.json').read_text())
meta.update(source=str(source),source_sha256=source_sha,candidate=str(out),candidate_sha256=sha(out),
    change='All-ray captured Canary Wharf HDR world replaces procedural sky; yaw90 points north glazing toward the open river direction. No geometry, furniture, surface materials, source lights, exposure or cameras changed. No additional Sun.',
    environment_provenance=pre['environment_provenance'],world_asset_sha256=pre['world_asset_sha256'],
    world_yaw_degrees=90,world_gain=pre['world_gain'],horizontal_card_measurements=measurements,
    current_horizontal_total_Y_ratio=ratio,photorealism_accepted=False,
    scope='Actual room trial, not adoption. Prior asset hold remains relevant: terrace/railings/near walls may mismatch reference, especially other facade directions. Current horizontal unoccluded 18% Lambert Y matched only; colour/direction/window transmission and room appearance are not matched. All rays share captured world, no camera-only backdrop.')
(D/'realism_refinement_r99.json').write_text(json.dumps(meta,indent=2))
print('CAPTURED_WORLD_R99_TRIAL_SAVED',ratio,flush=True)
