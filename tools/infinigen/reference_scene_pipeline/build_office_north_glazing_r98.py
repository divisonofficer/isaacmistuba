"""Three native full-height conference facade windows; separate candidate only."""
import bpy, json, sys, hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'modules/infinigen'))
sys.path.insert(0, str(Path(__file__).parent))
from infinigen.assets.objects.windows.window import WindowFactory
from cut_surface import remove_box_faces

D = ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
B = ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
source, out = B/'scene_candidate_r97.blend', B/'scene_candidate_r98.blend'
assert not out.exists()
# Do not branch from an unreviewed furniture trial.
review = json.loads((D/'breakout_r97_real_meeting_chairs/visual_review.json').read_text())
assert review['retain_bounded_chair_change'] is True
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
source_sha = sha(source)
assert review['source_sha256'] == source_sha
bpy.ops.wm.open_mainfile(filepath=str(source))
meta = json.loads((D/'realism_refinement_r97.json').read_text())
black = bpy.data.materials['R91_powder_coated_black_frame']
glass = bpy.data.materials['R91_physical_clear_glass']
control = dict(PanelHAmount=1, PanelVAmount=3, SubPanelHAmount=1,
               SubPanelVAmount=1, FrameWidth=.045, SubFrameWidth=.018,
               SubFrameThickness=.06, GlassThickness=.008)
records = []
for index, room, xa, xb in [(10,6,1.10,5.70),(11,7,6.30,9.70),(12,8,10.30,14.10)]:
    old = next(o for o in bpy.data.objects if o.type=='MESH'
               and o.name.startswith('WindowFactory(') and o.name.endswith(f'.spawn_asset({index})'))
    shell = [bpy.data.objects[f'office_0/{room}.{kind}'] for kind in ['wall','exterior']]
    width, height, bottom, plane = xb-xa, 2.53, .12, 21.945
    factory = WindowFactory(87430, curtain=False, shutter=False)
    original_sample = factory.sample_asset_params
    def controlled(*args, **kwargs):
        params = original_sample(*args, **kwargs)
        params.update(control)
        return params
    factory.sample_asset_params = controlled
    new = factory.create_asset(dimensions=(width-.045,height-.045,.12),open=False)
    new.name = f'Office02_r98_north_glazing_{index}'
    for i, material in enumerate(new.data.materials):
        if material == factory.params['Material']: new.data.materials[i] = glass
        elif material == factory.params['FrameMaterial']: new.data.materials[i] = black
    bpy.context.view_layer.update()
    assert abs(new.dimensions.x-width)<1e-4 and abs(new.dimensions.z-height)<1e-4
    new.location = ((xa+xb)/2,plane,0)
    bpy.context.view_layer.update()
    new.location.z += bottom-min((new.matrix_world@Vector(c)).z for c in new.bound_box)
    bpy.context.view_layer.update()
    cuts = [{'wall':wall.name,'removed_split_faces':remove_box_faces(
        wall,((xa+xb)/2,plane,bottom+height/2),(width+.003,.42,height+.003))} for wall in shell]
    assert all(row['removed_split_faces']>0 for row in cuts)
    removed = [o.name for o in old.children_recursive]+[old.name]
    if old.parent: old.parent.hide_render = True
    for o in list(old.children_recursive): bpy.data.objects.remove(o,do_unlink=True)
    bpy.data.objects.remove(old,do_unlink=True)
    new['reference_scene_owner'] = 'commercial_office_floor_02'
    new['program_key'] = f'north_native_fullheight_glazing_{index}'
    new['audit_kind'] = 'architectural_glazing'
    new['construction_source'] = 'WindowFactory controlled native geometry'
    # Actual shell triangle rays through pane interiors, not just bounds.
    tests = []
    for wall in shell:
        tree = BVHTree.FromPolygons([wall.matrix_world@v.co for v in wall.data.vertices],
                                   [tuple(p.vertices) for p in wall.data.polygons])
        for u in [.2,.5,.8]:
            for z in [.35,1.3,2.4]:
                hit = tree.ray_cast(Vector((xa+u*width,21.6,z)),Vector((0,1,0)),.7)[0]
                tests.append({'wall':wall.name,'x':xa+u*width,'z':z,'shell_clear':hit is None})
    assert all(test['shell_clear'] for test in tests)
    records.append({'object':new.name,'native_seed':87430,'parameters':control,
        'target_x_interval':[xa,xb],'target_bounds_z':[bottom,bottom+height],
        'plane_y':plane,'native_faces':len(new.data.polygons),'removed_objects':removed,
        'shell_cuts':cuts,'shell_pane_rays':tests})
bpy.ops.wm.save_as_mainfile(filepath=str(out))
assert sha(source)==source_sha
meta.update(source=str(source),source_sha256=source_sha,candidate=str(out),candidate_sha256=sha(out),
    change='Replace three punched north conference/meeting windows with native full-height black three-pane facade assemblies; cut both real shells. Preserve accepted bounded r97 chairs, all other furniture, lights, world and exposure.',
    north_glazing_records=records,photorealism_accepted=False,
    scope='Build and raw shell pane-ray checks only; saved-file validation and same-camera RGB comparison required. Blank exterior and remaining facade gaps still open.')
(D/'realism_refinement_r98.json').write_text(json.dumps(meta,indent=2))
print('NORTH_NATIVE_GLAZING_R98_SAVED',flush=True)
