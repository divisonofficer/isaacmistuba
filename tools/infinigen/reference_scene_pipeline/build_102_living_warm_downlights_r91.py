"""Extend the calibrated native living fixtures to unit 102; no scene acceptance."""
import bpy, json, hashlib, sys
from pathlib import Path
from mathutils import Vector
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(Path(__file__).parent))
from cut_surface import remove_box_faces
D = ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
B = ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full'
source, out = B/'scene_candidate_r90.blend', B/'scene_candidate_r91.blend'
assert not out.exists()
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
source_sha = sha(source)
bpy.ops.wm.open_mainfile(filepath=str(source))
meta = json.loads((D/'realism_refinement_r90.json').read_text())
ceiling = bpy.data.objects['living-room_0/1.ceiling']
cz = min((ceiling.matrix_world@Vector(v)).z for v in ceiling.bound_box)
ceiling.data = ceiling.data.copy()
old_light = bpy.data.objects['res03_area_102_living']
old_fixture = [o for o in bpy.context.scene.objects if o.get('program_key')=='102_living_ceiling_fixture']
assert len(old_fixture)==1 and old_light.data.energy>0
power = old_light.data.energy
removed = [old_light.name,old_fixture[0].name]
bpy.data.objects.remove(old_light,do_unlink=True)
bpy.data.objects.remove(old_fixture[0],do_unlink=True)
records=[]
for i, original in enumerate(meta['fixtures']):
    src = bpy.data.objects[original['object']]
    obj = src.copy()
    obj.data = src.data.copy()
    bpy.context.scene.collection.objects.link(obj)
    obj.name = f'Res03_r91_102_living_native_downlight_{i}'
    points=[obj.matrix_world@Vector(v) for v in obj.bound_box]
    x,y = 21.5-original['xy'][0],original['xy'][1]
    obj.location += Vector((x-(min(p.x for p in points)+max(p.x for p in points))/2,
                            y-(min(p.y for p in points)+max(p.y for p in points))/2,
                            cz+.004-max(p.z for p in points)))
    obj['program_key']='102_living_ceiling_fixture' if i==0 else f'102_living_native_downlight_{i}'
    assert len(obj.data.polygons)==6294
    cut=remove_box_faces(ceiling,(x,y,cz),(.07,.07,.06))
    assert cut>0
    light_source=bpy.data.objects[original['area_light']]
    light=light_source.copy()
    light.data=light_source.data.copy()
    light.name=f'Realism_102_living_downlight_{i}'
    bpy.context.scene.collection.objects.link(light)
    light.location=(x,y,cz-.009)
    light.data.energy=power/4
    emission=next(n for n in light.data.node_tree.nodes if n.type=='EMISSION')
    assert not emission.inputs['Strength'].is_linked
    emission.inputs['Strength'].default_value=1
    row=dict(original)
    row.update(object=obj.name,xy=[x,y],ceiling_z=cz,native_top_z=cz+.004,
               native_bottom_z=cz-.007,area_light=light.name,area_power=power/4,
               node_strength=1,removed_ceiling_split_faces=cut)
    records.append(row)
coves=[]
for obj in bpy.context.scene.objects:
    if obj.type!='MESH' or not str(obj.get('program_key','')).startswith('102_living_cove_led'):continue
    for i,material in enumerate(obj.data.materials):
        if not material or not material.use_nodes:continue
        material=material.copy();obj.data.materials[i]=material
        bs=next(n for n in material.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
        bb=material.node_tree.nodes.new('ShaderNodeBlackbody')
        bb.inputs['Temperature'].default_value=3200
        material.node_tree.links.new(bb.outputs['Color'],bs.inputs['Emission Color'])
        coves.append({'object':obj.name,'temperature_K':3200,
                      'emission_strength':bs.inputs['Emission Strength'].default_value})
assert len(records)==4 and coves
bpy.context.view_layer.update()
bpy.ops.wm.save_as_mainfile(filepath=str(out))
assert sha(source)==source_sha
meta.update(source=str(source),source_sha256=source_sha,candidate=str(out),candidate_sha256=sha(out),
    change='Unit102 living only: replace square ceiling fixture and central area with four native round recessed fixtures and 3200K transport lights. Existing transport power sum preserved; emission multipliers exactly1. Warm existing cove emission. All furniture, world, exposure and unit101 unchanged.',
    unit102_lighting={'fixtures':records,'coves':coves,'removed':removed,
                      'replaced_area_power':power,'summed_new_area_power':power},
    photorealism_accepted=False,
    scope='Native geometry and power graph contract, not measured photometry or room realism. Saved mounting/ceiling rays and identical-camera RGB comparison required.')
(D/'realism_refinement_r91.json').write_text(json.dumps(meta,indent=2))
print('UNIT102_NATIVE_WARM_LIGHTING_R91_SAVED',flush=True)
