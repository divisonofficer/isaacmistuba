"""Correct r93's hidden-backing assignment. Preserve real tile joints and geometry."""
import bpy, hashlib, json, sys
from pathlib import Path
R=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(Path(__file__).parent))
from surface_realism import grout_material
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
B=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full'
source=B/'scene_candidate_r93.blend'; out=B/'scene_candidate_r94.blend'
assert not out.exists()
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
source_sha=sha(source)
bpy.ops.wm.open_mainfile(filepath=str(source))
grout=grout_material('R94_local_warm_grout',(.30,.27,.23))
backings=[]
for name in ['bathroom_0/2.wall','bathroom_0/2.floor']:
    obj=bpy.data.objects[name];obj.data=obj.data.copy()
    obj.data.materials.clear();obj.data.materials.append(grout)
    for face in obj.data.polygons:face.material_index=0
    backings.append(name)
materials={}
for kind,old_name in [('wall','R93_native_warm_veined_stone'),('floor','R93_native_stone_floor')]:
    mat=bpy.data.materials[old_name].copy();mat.name='R94_native_stone_visible_'+kind
    n,l=mat.node_tree.nodes,mat.node_tree.links
    bs=next(x for x in n if x.type=='BSDF_PRINCIPLED')
    l.new(n['R93_tile_colour_variation'].outputs[0],bs.inputs['Base Color'])
    l.new(n['R93_grout_roughness'].inputs[1].links[0].from_socket,bs.inputs['Roughness'])
    l.new(n['R93_micro_relief_80um'].outputs['Normal'],bs.inputs['Normal'])
    n['R93_tile_dimensions_1p2_by_0p6m'].inputs[1].default_value=(.6,.6,1)
    materials[kind]=mat
records=[]
for obj in list(bpy.context.scene.objects):
    if not obj.name.startswith('Realism_bathroom_0/2_') or '_tile_' not in obj.name:continue
    kind='floor' if '_floor_tile_' in obj.name else 'wall'
    obj.data=obj.data.copy();mesh=obj.data;previous=mesh.uv_layers.active_index
    layer=mesh.uv_layers.get('R93_StoneMetres') or mesh.uv_layers.new(name='R93_StoneMetres')
    for face in mesh.polygons:
        normal=(obj.matrix_world.to_3x3().inverted().transposed()@face.normal).normalized()
        for li in face.loop_indices:
            p=obj.matrix_world@mesh.vertices[mesh.loops[li].vertex_index].co
            layer.data[li].uv=(p.x,p.y) if abs(normal.z)>.5 else ((p.y,p.z) if abs(normal.x)>.5 else (p.x,p.z))
    mesh.uv_layers.active_index=previous
    old=[m.name if m else None for m in mesh.materials]
    mesh.materials.clear();mesh.materials.append(materials[kind])
    for face in mesh.polygons:face.material_index=0
    records.append({'object':obj.name,'kind':kind,'old_materials':old,'new_material':materials[kind].name,'metric_uv':'R93_StoneMetres'})
assert len(records)==131,len(records)
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert sha(source)==source_sha
meta=json.loads((D/'realism_refinement_r93.json').read_text())
meta.update(source=str(source),source_sha256=source_sha,candidate=str(out),candidate_sha256=sha(out),
    change='Correct r93 assignment: stone on 131 actual visible tile solids, warm grout on backing, retain physical tile joints/bevels. No shader-only grout. No lights/camera/world changes.',
    photorealism_accepted=False)
meta['stone_finish'].update(contract_version=2,surfaces=records,backing_objects=backings,tile_size_m=[.6,.6],
    grout_width_m=.003,grout_normal_distance_m=0,physical_tile_recess_m=.0015,
    diagnosis='actual_stone_surface_diagnosis_r93.json',
    limitation='Authored native procedural veins, not scanned PBR. Existing 600mm tile geometry retained, not yet reference large-format conversion. Only 101 main bathroom. RGB screening required.')
(D/'realism_refinement_r94.json').write_text(json.dumps(meta,indent=2))
print('VISIBLE_TILE_SOURCE94_SAVED',len(records),flush=True)
