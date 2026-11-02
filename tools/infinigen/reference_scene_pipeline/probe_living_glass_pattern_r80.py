"""Read-only same-camera crop: isolate glass normal versus roughness effects."""
import datetime
import hashlib
import json
import math
import os
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[3]
REF = ROOT / 'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
OUT = REF / 'living_glass_pattern_probe_r80'
OUT.mkdir(exist_ok=True)
STATE = OUT / 'job.json'
assert not STATE.exists()
SOURCE = ROOT / 'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r80.blend'
digest = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
state = {'pid': os.getpid(), 'phase': 'reading_source', 'device': 'CPU',
         'scene_candidate_saved': False, 'photorealism_accepted': False}


def checkpoint(**changes):
    state.update(changes, updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    STATE.write_text(json.dumps(state, indent=2) + '\n')
    print(json.dumps(state), flush=True)


try:
    checkpoint()
    source_hash = digest(SOURCE)
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
    scene = bpy.context.scene
    glass = next(o for o in scene.objects if o.get('program_key') == '101_living_glass')
    assert len(glass.data.materials) == 1
    original = glass.data.materials[0]
    view = next(v for v in json.loads((REF / 'furniture_r80_window_caustics/views.json').read_text())
                if v['name'] == '101_living')
    camera_data = bpy.data.cameras.new('Diagnostic_same_review_camera')
    camera = bpy.data.objects.new(camera_data.name, camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera.location = view['location']
    camera.rotation_euler = (Vector(view['target']) - camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera_data.angle = math.radians(view['hfov'])
    camera_data.clip_start, camera_data.clip_end = .05, 150
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 64
    scene.cycles.seed = 47
    scene.cycles.use_denoising = False
    scene.render.threads_mode = 'FIXED'
    scene.render.threads = 4
    scene.render.resolution_x, scene.render.resolution_y = 1280, 960
    scene.render.resolution_percentage = 100
    scene.render.use_border = True
    scene.render.use_crop_to_border = True
    scene.render.border_min_x, scene.render.border_max_x = .70, .95
    scene.render.border_min_y, scene.render.border_max_y = .20, .58
    scene.render.use_persistent_data = True
    scene.render.image_settings.file_format = 'PNG'
    scene.view_settings.view_transform = 'AgX'
    scene.view_settings.exposure = 0
    # Match the existing review renderer's documented overrides in every case.
    background = scene.world.node_tree.nodes.get('Background')
    if background:
        background.inputs['Strength'].default_value = .45
    for obj in scene.objects:
        if obj.type == 'LIGHT' and obj.data.type == 'AREA' and obj.parent and 'Window' in obj.parent.name:
            area = obj.data.size * (obj.data.size_y if obj.data.shape == 'RECTANGLE' else obj.data.size)
            obj.data.energy = 65 * max(area, .1)
    rows = []
    cases = [('A_original', False, False), ('B_no_normal', True, False),
             ('C_constant_roughness', False, True), ('D_no_normal_constant_roughness', True, True)]
    for name, no_normal, constant_roughness in cases:
        material = original.copy()
        material.name = 'DIAGNOSTIC_' + name
        glass.data.materials[0] = material
        shaders = [node for node in material.node_tree.nodes if node.type == 'BSDF_PRINCIPLED']
        assert len(shaders) == 1
        shader = shaders[0]
        removed = []
        sockets = (['Normal', 'Coat Normal'] if no_normal else []) + (['Roughness'] if constant_roughness else [])
        for socket_name in sockets:
            socket = shader.inputs[socket_name]
            for link in list(socket.links):
                removed.append({'socket': socket_name, 'source_node': link.from_node.name})
                material.node_tree.links.remove(link)
        if constant_roughness:
            shader.inputs['Roughness'].default_value = .015
        checkpoint(phase='rendering_diagnostic', case=name)
        path = OUT / (name + '.png')
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        rows.append({'name': name, 'path': str(path), 'sha256': digest(path),
                     'normal_disconnected': no_normal, 'constant_roughness': .015 if constant_roughness else None,
                     'removed_links': removed, 'glass_hidden': glass.hide_render})
        glass.data.materials[0] = original
        bpy.data.materials.remove(material)
    assert digest(SOURCE) == source_hash
    result = {'source': str(SOURCE), 'source_sha256': source_hash, 'source_unchanged': True,
              'camera': view, 'resolution_before_crop': [1280, 960],
              'border': [.70, .95, .20, .58], 'samples': 64, 'seed': 47, 'denoising': False,
              'rows': rows, 'scene_candidate_saved': False, 'photorealism_accepted': False,
              'scope': 'Same actual-source80 camera/wall crop and lighting. Only101 living glass shader socket isolation. No hidden glass, no scene save, no production material recommendation or full-room acceptance before image review.'}
    (OUT / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
    checkpoint(phase='diagnostics_complete_review_pending')
except Exception as error:
    checkpoint(phase='failed', error=str(error))
    raise
