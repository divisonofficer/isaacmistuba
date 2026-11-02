"""Native Infinigen marble adapter and removal of wet-room PVC trim; RGB trial only."""
import bpy,json,hashlib,sys
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(R/'modules/infinigen'));sys.path.insert(0,str(Path(__file__).parent))
from infinigen.core import surface
from infinigen.assets.materials.ceramic.marble import shader_marble
from cut_surface import remove_box_faces
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
B=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full'
source,out=B/'scene_candidate_r92.blend',B/'scene_candidate_r93.blend';assert not out.exists()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();source_sha=sha(source)
bpy.ops.wm.open_mainfile(filepath=str(source))
mat=surface.shaderfunc_to_material(shader_marble);mat.name='R93_native_warm_veined_stone'
n,l=mat.node_tree.nodes,mat.node_tree.links
bs=next(x for x in n if x.type=='BSDF_PRINCIPLED')
vein=next(x for x in n if x.type=='MATH' and x.operation=='MULTIPLY').outputs[0]
output=next(x for x in n if x.type=='OUTPUT_MATERIAL' and x.is_active_output)
for link in list(output.inputs['Displacement'].links):l.remove(link)
def node(kind,name):
    x=n.new(kind);x.name=name;return x
def math_node(operation,a,b=None):
    x=node('ShaderNodeMath','R93_'+operation);x.operation=operation
    if isinstance(a,(float,int)):x.inputs[0].default_value=a
    else:l.new(a,x.inputs[0])
    if b is not None:
        if isinstance(b,(float,int)):x.inputs[1].default_value=b
        else:l.new(b,x.inputs[1])
    return x.outputs[0]
def map_value(value,low,high,name):
    x=node('ShaderNodeMapRange',name);x.inputs['To Min'].default_value=low;x.inputs['To Max'].default_value=high
    l.new(value,x.inputs['Value']);return x.outputs['Result']
uv=node('ShaderNodeUVMap','R93_metric_surface_coordinates');uv.uv_map='R93_StoneMetres'
ratio=node('ShaderNodeVectorMath','R93_tile_dimensions_1p2_by_0p6m');ratio.operation='DIVIDE'
l.new(uv.outputs['UV'],ratio.inputs[0]);ratio.inputs[1].default_value=(1.2,.6,1)
cell=node('ShaderNodeVectorMath','R93_tile_cell_id');cell.operation='FLOOR';l.new(ratio.outputs[0],cell.inputs[0])
random=node('ShaderNodeTexWhiteNoise','R93_tile_variation');random.noise_dimensions='3D';l.new(cell.outputs[0],random.inputs['Vector'])
sep=node('ShaderNodeSeparateXYZ','R93_tile_fraction');l.new(ratio.outputs[0],sep.inputs[0])
masks=[]
for axis,edge in [('X',.001/1.2),('Y',.001/.6)]:
    frac=math_node('FRACT',sep.outputs[axis])
    masks.append(math_node('MAXIMUM',math_node('LESS_THAN',frac,edge),math_node('GREATER_THAN',frac,1-edge)))
grout=math_node('MAXIMUM',*masks)
palette=node('ShaderNodeValToRGB','R93_greige_stone_and_light_veins')
palette.color_ramp.elements[0].color=(.34,.30,.25,1)
palette.color_ramp.elements[1].color=(.63,.57,.49,1);l.new(vein,palette.inputs[0])
colour=node('ShaderNodeMixRGB','R93_tile_colour_variation');colour.blend_type='MULTIPLY';colour.inputs[0].default_value=1
l.new(palette.outputs['Color'],colour.inputs[1]);l.new(map_value(random.outputs['Value'],.985,1.015,'R93_colour_plus_minus1p5pct'),colour.inputs[2])
mix=node('ShaderNodeMixRGB','R93_stone_grout_colour');l.new(grout,mix.inputs[0]);l.new(colour.outputs[0],mix.inputs[1]);mix.inputs[2].default_value=(.30,.26,.22,1)
l.new(mix.outputs[0],bs.inputs['Base Color']);bs.inputs['Metallic'].default_value=0;bs.inputs['IOR'].default_value=1.5
geo=node('ShaderNodeNewGeometry','R93_world_metres')
def noise(scale,name):
    x=node('ShaderNodeTexNoise',name);x.inputs['Scale'].default_value=scale;x.inputs['Detail'].default_value=2
    l.new(geo.outputs['Position'],x.inputs['Vector']);return x.outputs['Fac']
base=node('ShaderNodeValue','R93_base_roughness');base.outputs[0].default_value=.37
rough=math_node('ADD',base.outputs[0],map_value(noise(.8,'R93_macro_1p25m'),-.035,.035,'R93_macro_roughness'))
rough=math_node('ADD',rough,map_value(noise(40,'R93_meso_2p5cm'),-.025,.025,'R93_meso_roughness'))
rough=math_node('ADD',rough,map_value(random.outputs['Value'],-.015,.015,'R93_per_tile_roughness'))
r_mix=node('ShaderNodeMixRGB','R93_grout_roughness');l.new(grout,r_mix.inputs[0]);l.new(rough,r_mix.inputs[1]);r_mix.inputs[2].default_value=(.65,.65,.65,1);l.new(r_mix.outputs[0],bs.inputs['Roughness'])
micro=node('ShaderNodeBump','R93_micro_relief_80um');micro.inputs['Distance'].default_value=.00008;micro.inputs['Strength'].default_value=.25
l.new(noise(800,'R93_micro_1p25mm'),micro.inputs['Height'])
joint=node('ShaderNodeBump','R93_grout_normal_recess_1p2mm');joint.inputs['Distance'].default_value=.0012;joint.inputs['Strength'].default_value=1
l.new(math_node('SUBTRACT',1,grout),joint.inputs['Height']);l.new(micro.outputs['Normal'],joint.inputs['Normal']);l.new(joint.outputs['Normal'],bs.inputs['Normal'])
records=[]
for name in ['bathroom_0/2.wall','bathroom_0/2.floor']:
    obj=bpy.data.objects[name];obj.data=obj.data.copy();mesh=obj.data
    previous=mesh.uv_layers.active_index
    uv_layer=mesh.uv_layers.new(name='R93_StoneMetres')
    for face in mesh.polygons:
        normal=(obj.matrix_world.to_3x3().inverted().transposed()@face.normal).normalized()
        for loop_index in face.loop_indices:
            point=obj.matrix_world@mesh.vertices[mesh.loops[loop_index].vertex_index].co
            if abs(normal.z)>.5:coords=(point.x-.1145347,point.y-3.1145347)
            elif abs(normal.x)>.5:coords=(point.y-3.1145347,point.z-.1145347)
            else:coords=(point.x-.1145347,point.z-.1145347)
            uv_layer.data[loop_index].uv=coords
    if len(mesh.uv_layers)>1:mesh.uv_layers.active_index=previous
    replacement=mat
    if name.endswith('.floor'):
        replacement=mat.copy();replacement.name='R93_native_stone_floor';replacement.node_tree.nodes['R93_base_roughness'].outputs[0].default_value=.43
    old=[m.name for m in mesh.materials];mesh.materials.clear();mesh.materials.append(replacement)
    for face in mesh.polygons:face.material_index=0
    records.append({'object':name,'old_materials':old,'new_material':replacement.name,'metric_uv':'R93_StoneMetres','geometry_faces':len(mesh.polygons)})
skirt=bpy.data.objects['skirtingboard_support'];skirt.data=skirt.data.copy()
outside=[skirt.matrix_world@v.co for v in skirt.data.vertices
         if not (-.01<= (skirt.matrix_world@v.co).x<=3.01 and 2.99<=(skirt.matrix_world@v.co).y<=6.01)]
removed=remove_box_faces(skirt,(1.5,4.5,.18),(3,3,.30));assert removed>0
tree=BVHTree.FromPolygons([skirt.matrix_world@v.co for v in skirt.data.vertices],[tuple(f.vertices) for f in skirt.data.polygons])
distances=[tree.find_nearest(p)[3] for p in outside]
assert distances and max(distances)<1e-4
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert sha(source)==source_sha
meta=json.loads((D/'realism_refinement_r92.json').read_text())
meta.update(source=str(source),source_sha256=source_sha,candidate=str(out),candidate_sha256=sha(out),
    change='101 main bathroom only: native Infinigen marble graph adapted to warm greige veins, independent roughness scales and metric2mm grout shading; remove PVC trim inside exact room box. Preserve real shower92,all furniture,lights,world and cameras.',
    stone_finish={'native_source':'modules/infinigen/infinigen/assets/materials/ceramic/marble.py',
        'native_source_sha256':sha(R/'modules/infinigen/infinigen/assets/materials/ceramic/marble.py'),
        'surfaces':records,'tile_size_m':[1.2,.6],'grout_width_m':.002,
        'grout_normal_distance_m':.0012,'micro_normal_distance_m':.00008,
        'wall_roughness_base':.37,'floor_roughness_base':.43,'skirting_removed_split_faces':removed,
        'outside_skirting_vertex_samples':len(distances),'outside_skirting_max_surface_distance_m':max(distances)},
    photorealism_accepted=False,
    scope='Authored procedural native material, not photographed scan/measured BRDF. Grout recess and micro relief are normal shading, not displaced mesh geometry. Actual outer wall/floor geometry unchanged; removed local PVC trim. Outside trim vertex samples are bounded preservation evidence,not full topology/volume certification. RGB/reference and saved-source gates required.')
(D/'realism_refinement_r93.json').write_text(json.dumps(meta,indent=2))
print('NATIVE_STONE_BATHROOM_R93_SAVED',removed,max(distances),flush=True)
