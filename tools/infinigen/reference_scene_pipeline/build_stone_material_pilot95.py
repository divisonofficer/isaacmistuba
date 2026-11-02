"""Two fixed-light actual tile samples before another expensive room trial."""
import bpy, json, hashlib, sys
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3]
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/stone_material_pilot95'
D.mkdir(exist_ok=True)
S=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r94.blend'
assert not (D/'baseline.blend').exists() and not (D/'candidate.blend').exists()
source_sha=hashlib.sha256(S.read_bytes()).hexdigest()
bpy.ops.wm.read_factory_settings(use_empty=True)
with bpy.data.libraries.load(str(S),link=False) as (src,dst):
    dst.objects=['Realism_bathroom_0/2_wall_tile_83']
obj=dst.objects[0];bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.update()
points=[obj.matrix_world@v.co for v in obj.data.vertices]
lo=Vector(tuple(min(p[k] for p in points) for k in range(3)))
hi=Vector(tuple(max(p[k] for p in points) for k in range(3)))
center=(lo+hi)/2
views=[{'name':'actual_tile_patch','location':list(center+Vector((-1.3,-.6,.3))),
        'target':list(center),'overview':True,'ortho_scale':.85,'render_width':640,'samples':48}]
for j,(delta,power,size) in enumerate([((-1,-.7,1.1),65,.7),((-1,.8,.3),25,.4)]):
    ld=bpy.data.lights.new('Pilot95_area'+str(j),'AREA');ld.energy=power;ld.size=size
    light=bpy.data.objects.new(ld.name,ld);bpy.context.scene.collection.objects.link(light)
    light.location=center+Vector(delta);light.rotation_euler=(center-light.location).to_track_quat('-Z','Y').to_euler()
w=bpy.data.worlds.new('Pilot95_neutral_world');w.use_nodes=True
w.node_tree.nodes.get('Background').inputs['Strength'].default_value=.12;bpy.context.scene.world=w
mat=obj.data.materials[0]
bpy.ops.wm.save_as_mainfile(filepath=str(D/'baseline.blend'))
mat=mat.copy();mat.name='Pilot95_native_cloudy_stone';obj.data.materials[0]=mat
n,l=mat.node_tree.nodes,mat.node_tree.links
native_mix=next(x for x in n if x.type=='MIX' and x.inputs[6].is_linked and x.inputs[7].is_linked
                and x.inputs[6].links[0].from_node.type=='TEX_NOISE' and x.inputs[7].links[0].from_node.type=='TEX_NOISE')
cloud=n.new('ShaderNodeValToRGB');cloud.name='Pilot95_native_mineral_base'
cloud.color_ramp.elements[0].position=.20;cloud.color_ramp.elements[0].color=(.27,.24,.20,1)
cloud.color_ramp.elements[1].position=.80;cloud.color_ramp.elements[1].color=(.46,.42,.36,1)
l.new(native_mix.outputs[2],cloud.inputs[0])
vein=n['R93_greige_stone_and_light_veins'].inputs[0].links[0].from_socket
scale=n.new('ShaderNodeMath');scale.name='Pilot95_restrained_vein_contrast';scale.operation='MULTIPLY'
l.new(vein,scale.inputs[0]);scale.inputs[1].default_value=.35
mix=n.new('ShaderNodeMixRGB');mix.name='Pilot95_mineral_and_veins'
l.new(scale.outputs[0],mix.inputs[0]);l.new(cloud.outputs[0],mix.inputs[1]);mix.inputs[2].default_value=(.55,.50,.43,1)
l.new(mix.outputs[0],n['R93_tile_colour_variation'].inputs[1])
bpy.ops.wm.save_as_mainfile(filepath=str(D/'candidate.blend'))
assert hashlib.sha256(S.read_bytes()).hexdigest()==source_sha
(D/'views.json').write_text(json.dumps(views,indent=2))
(D/'scope.json').write_text(json.dumps({'source':str(S),'source_sha256':source_sha,
    'source_unchanged':True,'actual_tile_object':obj.name,'geometry_unchanged':True,
    'baseline':str(D/'baseline.blend'),'candidate':str(D/'candidate.blend'),
    'change':'Reuse native marble base noise as cloudy mineral colour; reduce original vein contrast, retain tile randomisation, roughness and micro-normal. No tile geometry or diagnostic lights changed.',
    'world_coordinates_not_generated':'Native source uses TextureCoord.Object; no repeated-generated-coordinate defect asserted.',
    'photorealism_accepted':False,
    'scope':'One actual tile sample at native size under controlled diagnostic lights. Not a new residential source revision or room/reference acceptance.'},indent=2))
print('STONE_MATERIAL_PILOT95_SAVED',flush=True)
