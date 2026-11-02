"""Extend the calibrated native living fixtures to unit 102; no scene acceptance."""
import bpy, json, hashlib, sys, math
from pathlib import Path
from mathutils import Vector
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(Path(__file__).parent))
from cut_surface import remove_box_faces
D = ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
B = ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full'
source, out = B/'scene_candidate_r95.blend', B/'scene_candidate_r96.blend'
assert not out.exists()
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
source_sha = sha(source)
bpy.ops.wm.open_mainfile(filepath=str(source))
meta = json.loads((D/'realism_refinement_r95.json').read_text())
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
    obj.name = f'Res03_r96_102_living_native_downlight_{i}'
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
    light.data.energy=power*.4/4
    emission=next(n for n in light.data.node_tree.nodes if n.type=='EMISSION')
    assert not emission.inputs['Strength'].is_linked
    emission.inputs['Strength'].default_value=1
    blackbodies=[n for n in light.data.node_tree.nodes if n.type=='BLACKBODY'];assert len(blackbodies)==1
    blackbodies[0].inputs['Temperature'].default_value=3500
    row=dict(original)
    row.update(object=obj.name,xy=[x,y],ceiling_z=cz,native_top_z=cz+.004,
               native_bottom_z=cz-.007,area_light=light.name,area_power=power*.4/4,temperature_K=3500,
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
        bb.inputs['Temperature'].default_value=3500
        bs.inputs['Emission Strength'].default_value*=.5
        material.node_tree.links.new(bb.outputs['Color'],bs.inputs['Emission Color'])
        coves.append({'object':obj.name,'temperature_K':3500,
                      'emission_strength':bs.inputs['Emission Strength'].default_value})
# Neutral window-side fill replaces part of the old central fill; not a measured daylight calibration.
ld=bpy.data.lights.new('Res03_r96_102_daylight_window_fill','AREA');ld.shape='RECTANGLE'
ld.size=1.3;ld.size_y=1.6;ld.energy=power*.6;ld.use_nodes=True
em=next(n for n in ld.node_tree.nodes if n.type=='EMISSION');em.inputs['Strength'].default_value=1
bb=ld.node_tree.nodes.new('ShaderNodeBlackbody');bb.inputs['Temperature'].default_value=5500
ld.node_tree.links.new(bb.outputs['Color'],em.inputs['Color'])
window_fill=bpy.data.objects.new(ld.name,ld);bpy.context.scene.collection.objects.link(window_fill)
window_fill.location=(21.33,7.8,1.65);window_fill.rotation_euler=(0,math.pi/2,0)
window_fill['reference_scene_owner']='dual_unit_residential_floor_03'
window_fill['program_key']='102_living_window_daylight_fill';window_fill['audit_kind']='lighting'
daylight={'object':window_fill.name,'power':ld.energy,'temperature_K':5500,'node_strength':1,
          'position':list(window_fill.location),'size_m':[ld.size,ld.size_y]}
assert abs(sum(row['area_power'] for row in records)+ld.energy-power)<1e-6
assert len(records)==4 and coves
bpy.context.view_layer.update()
bpy.ops.wm.save_as_mainfile(filepath=str(out))
assert sha(source)==source_sha
meta.update(source=str(source),source_sha256=source_sha,candidate=str(out),candidate_sha256=sha(out),
    change='Unit102 living mixed-light trial from retained95: four native3500K practical fixtures receive40pct of former central AREA power; remaining60pct becomes5500K east-window-side fill. Cove3500K emission halved. Existing AREA watt sum retained, not equal luminous flux or brightness; other rooms, furniture,world/exposure unchanged.',
    unit102_lighting={'fixtures':records,'coves':coves,'removed':removed,
                      'replaced_area_power':power,'summed_new_area_power':power,'daylight_fill':daylight,'warm_practical_power_fraction':.4},
    photorealism_accepted=False,
    scope='Native geometry and power graph contract, not measured photometry or room realism. Saved mounting/ceiling rays and identical-camera RGB comparison required.')
(D/'realism_refinement_r96.json').write_text(json.dumps(meta,indent=2))
print('UNIT102_MIXED_LIGHTING_R96_SAVED',flush=True)
