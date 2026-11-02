"""Urban HDR trial with measured ambient and replacement solar contribution.

All rays share the same world. No camera-only background or exposure changes.
The added Sun replaces the procedural world's measured Sun-disc contribution;
existing scene lights remain unchanged. This is a hybrid lighting trial.
"""
import datetime
import hashlib
import json
import math
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
REF = ROOT / 'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
SOURCE, OUTPUT = BASE/'scene_candidate_r88.blend', BASE/'scene_candidate_r89.blend'
ASSETS = ROOT/'data/venue_refs/floor_plans_v3/environment_assets'
HDR = ASSETS/'urban_courtyard_02_4k.hdr'
STAGE = REF/'urban_environment_r89_calibration'
assert not OUTPUT.exists() and not STAGE.exists()
STAGE.mkdir()
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
source_hash = sha(SOURCE)
provenance = next(x for x in json.loads((ASSETS/'urban_candidates_download_receipts.json').read_text())
                  if x['id'] == 'urban_courtyard_02')
assert sha(HDR) == provenance['sha256']
bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
main = bpy.context.scene
original_world = main.world


def background(world):
    output = next(n for n in world.node_tree.nodes if n.type == 'OUTPUT_WORLD' and n.is_active_output)
    bg = output.inputs['Surface'].links[0].from_node
    assert bg.type == 'BACKGROUND'
    return bg


original_bg = background(original_world)
original_sky = original_bg.inputs['Color'].links[0].from_node
assert original_sky.type == 'TEX_SKY' and original_sky.sky_type == 'NISHITA' and original_sky.sun_disc
assert original_bg.name != 'Background', 'Legacy renderer overwrites this node; preserve actual authored strength'
original_strength = original_bg.inputs['Strength'].default_value
phi = math.pi/2 - original_sky.sun_rotation
elevation = original_sky.sun_elevation
sun_direction = Vector((math.cos(elevation)*math.cos(phi), math.cos(elevation)*math.sin(phi), math.sin(elevation)))
existing_suns = [{'name': o.name, 'energy': o.data.energy, 'color': list(o.data.color),
                  'matrix_world': [list(v) for v in o.matrix_world]}
                 for o in main.objects if o.type == 'LIGHT' and o.data.type == 'SUN']

reference_world = original_world.copy()
reference_sky = background(reference_world).inputs['Color'].links[0].from_node
world = original_world.copy()
world.name = 'R89_urban_HDR_measured_solar_replacement'
tree = world.node_tree
env = tree.nodes.new('ShaderNodeTexEnvironment')
env.name = 'R89_real_urban_courtyard_HDR'
env.image = bpy.data.images.load(str(HDR), check_existing=False)
assert env.image.is_float and env.image.colorspace_settings.name != 'sRGB'
env.image.pack()
assert sha(HDR) == hashlib.sha256(env.image.packed_file.data).hexdigest()
gain_node = tree.nodes.new('ShaderNodeVectorMath')
gain_node.operation = 'SCALE'
gain_node.name = 'R89_measured_ambient_gain'
gain_node.inputs['Scale'].default_value = 1
tree.links.new(env.outputs['Color'], gain_node.inputs[0])
tree.links.new(gain_node.outputs['Vector'], background(world).inputs['Color'])

probe = bpy.data.scenes.new('R89_ambient_solar_transfer_probe')
probe.render.engine = 'CYCLES'
probe.cycles.device = 'CPU'
probe.cycles.samples = 2048
probe.cycles.seed = 47
probe.cycles.use_denoising = False
probe.render.threads_mode = 'FIXED'
probe.render.threads = 4
probe.render.resolution_x = probe.render.resolution_y = 16
probe.render.resolution_percentage = 100
probe.render.image_settings.file_format = 'OPEN_EXR'
probe.render.image_settings.color_depth = '32'
probe.view_settings.exposure = 0
mesh = bpy.data.meshes.new('R89_diagnostic_card_not_saved')
mesh.from_pydata([(-1,-1,0), (1,-1,0), (1,1,0), (-1,1,0)], [], [(0,1,2,3)])
card = bpy.data.objects.new(mesh.name, mesh)
probe.collection.objects.link(card)
material = bpy.data.materials.new('R89_diagnostic_Lambert018')
material.use_nodes = True
material.node_tree.nodes.clear()
diffuse = material.node_tree.nodes.new('ShaderNodeBsdfDiffuse')
diffuse.inputs['Color'].default_value = (.18,.18,.18,1)
output = material.node_tree.nodes.new('ShaderNodeOutputMaterial')
material.node_tree.links.new(diffuse.outputs[0], output.inputs['Surface'])
mesh.materials.append(material)
camera_data = bpy.data.cameras.new('R89_probe_camera_not_saved')
camera = bpy.data.objects.new(camera_data.name, camera_data)
probe.collection.objects.link(camera)
camera.location = (0,0,1)
camera.rotation_euler = (0,0,0)
camera_data.type = 'ORTHO'
camera_data.ortho_scale = .2
probe.camera = camera
sun_data = bpy.data.lights.new('R89_procedural_world_solar_replacement', 'SUN')
sun = bpy.data.objects.new(sun_data.name, sun_data)
probe.collection.objects.link(sun)
sun.rotation_euler = (-sun_direction).to_track_quat('-Z','Y').to_euler()
sun_data.angle = original_sky.sun_size
sun_data.energy = 1
sun_data.cycles.is_caustics_light = original_world.cycles.is_caustics_light
rows = []


def measure(name, which_world, visible_sun):
    probe.world = which_world
    sun.hide_render = not visible_sun
    path = STAGE/(name+'.exr')
    probe.render.filepath = str(path)
    bpy.ops.render.render(write_still=True, scene=probe.name)
    image = bpy.data.images.load(str(path), check_existing=False)
    values = np.empty(len(image.pixels), dtype=np.float32)
    image.pixels.foreach_get(values)
    channels = len(values)//(16*16)
    rgb = values.reshape(16,16,channels)[4:12,4:12,:3].mean(axis=(0,1))
    bpy.data.images.remove(image)
    row = {'case': name, 'file': str(path), 'sha256': sha(path), 'mean_linear_RGB': rgb.tolist(),
           'mean_linear_Y': float(rgb @ np.array([.2126,.7152,.0722])),
           'replacement_sun_visible': visible_sun, 'replacement_sun_energy': sun_data.energy}
    rows.append(row)
    return rgb, row['mean_linear_Y']


reference_sky.sun_disc = False
a_rgb, a_y = measure('A_reference_diffuse_sky', reference_world, False)
reference_sky.sun_disc = True
b_rgb, b_y = measure('B_reference_sky_with_solar_disc', reference_world, False)
c_rgb, c_y = measure('C_HDR_unscaled_no_sun', world, False)
ambient_gain = a_y/c_y
assert .001 < ambient_gain < 100
gain_node.inputs['Scale'].default_value = ambient_gain
d_rgb, d_y = measure('D_HDR_matched_ambient', world, False)
assert abs(d_y/a_y-1) < .03
solar_rgb = b_rgb-a_rgb
solar_y = b_y-a_y
assert solar_y > .0001 and float(solar_rgb.min()) > 0, ('Unstable reference solar difference', solar_rgb.tolist())
sun_data.color = tuple(float(x) for x in solar_rgb/solar_rgb.max())
e_rgb, e_y = measure('E_HDR_with_unit_replacement_sun', world, True)
assert e_y > d_y
sun_energy = solar_y/(e_y-d_y)
assert .0001 < sun_energy < 1000
sun_data.energy = sun_energy
f_rgb, f_y = measure('F_HDR_matched_ambient_and_solar', world, True)
solar_ratio = (f_y-d_y)/solar_y
assert abs(f_y/b_y-1) < .05 and abs(solar_ratio-1) < .12, (f_y/b_y, solar_ratio)
calibration = {'source': str(SOURCE), 'source_sha256': source_hash, 'rows': rows,
               'ambient_gain': ambient_gain, 'sun_energy': sun_energy,
               'solar_color': list(sun_data.color), 'solar_direction_world': list(sun_direction),
               'solar_angle': sun_data.angle, 'ambient_Y_match_ratio': d_y/a_y,
               'total_Y_match_ratio': f_y/b_y, 'solar_difference_match_ratio': solar_ratio,
               'scope': 'Unoccluded horizontal18percentLambert card,16x16/2048spp CPU/no denoise. Matches photopic ambient and procedural solar contribution only;not calibrated lux,window transmission,room colour/reference/photo acceptance. Existing main-scene lights excluded fromprobe andpreserved.'}
(STAGE/'results.json').write_text(json.dumps(calibration, indent=2)+'\n')
sun.hide_render = False
probe.collection.objects.unlink(sun)
main.collection.objects.link(sun)
main.world = world
for obj in [card,camera]:
    bpy.data.objects.remove(obj, do_unlink=True)
bpy.data.scenes.remove(probe)
assert bpy.context.scene == main
assert sha(SOURCE) == source_hash
bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT))
metadata = {'source': str(SOURCE), 'source_sha256': source_hash, 'candidate': str(OUTPUT),
            'candidate_sha256': sha(OUTPUT), 'environment_provenance': {**provenance, 'downloaded_file': str(HDR)},
            'calibration': str(STAGE/'results.json'), 'calibration_sha256': sha(STAGE/'results.json'),
            'environment_yaw': 0, 'authored_background_strength_preserved': original_strength,
            'ambient_gain': ambient_gain, 'replacement_sun': sun.name, 'existing_suns_preserved': existing_suns,
            'photorealism_accepted': False, 'retained_revision': 88,
            'change': 'CapturedurbanHDR replaces procedural diffuseworld;calibrated directionalSun replaces measured former procedural solar contribution. Allrays shareworld;existing scene lights,geometry/materials/cameras/exposure unchanged.',
            'limits': 'Hybridlighting,not untouchedcapturedradiance. Overcastforeignurban environment isnot Korean/reference proof. Sun-versus-skyline angular consistency,actualwindowview/roomshadows/brightness andbothreference+photo quality require directsame-camera andfresh review. No fullscene/navigation/dataset approval.'}
(REF/'realism_refinement_r89.json').write_text(json.dumps(metadata, indent=2)+'\n')
print('URBAN_ENVIRONMENT_R89_SAVED', flush=True)
