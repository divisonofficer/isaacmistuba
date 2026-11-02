"""Screen generated albedo on an existing actual tile under identical diagnostic lights."""
import bpy,json,hashlib
from pathlib import Path
R=Path(__file__).resolve().parents[3]
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
P=D/'stone_material_pilot96_authored';P.mkdir(exist_ok=True)
S=D/'stone_material_pilot95/baseline.blend';out=P/'candidate.blend';assert not out.exists()
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
before=sha(S);bpy.ops.wm.open_mainfile(filepath=str(S))
obj=bpy.data.objects['Realism_bathroom_0/2_wall_tile_83'];mat=obj.data.materials[0].copy();mat.name='Pilot96_authored_greige_stone';obj.data.materials[0]=mat
n,l=mat.node_tree.nodes,mat.node_tree.links
uv=n['R93_metric_surface_coordinates'].outputs['UV']
def vec(name,op,a,b=None):
 x=n.new('ShaderNodeVectorMath');x.name=name;x.operation=op;l.new(a,x.inputs[0])
 if b is not None:
  if isinstance(b,tuple):x.inputs[1].default_value=b
  else:l.new(b,x.inputs[1])
 return x.outputs['Vector']
# 600 mm native tile spans 30% of a 2 m texture sample; per-tile crop remains inside image.
scaled=vec('Pilot96_cell_metres','SCALE',uv);n['Pilot96_cell_metres'].inputs['Scale'].default_value=1/.6
cell=vec('Pilot96_cell_id','FLOOR',scaled)
local=vec('Pilot96_tile_local','FRACTION',scaled)
local=vec('Pilot96_physical_texture_scale','MULTIPLY',local,(.3,.3,0))
rnd=n.new('ShaderNodeTexWhiteNoise');rnd.name='Pilot96_tile_crop';l.new(cell,rnd.inputs['Vector'])
offset=vec('Pilot96_crop_offset','MULTIPLY',rnd.outputs['Color'],(.7,.7,0))
coord=vec('Pilot96_no_wrapping_crop','ADD',local,offset)
image_path=R/'assets/opticalnav_curated/authored_stone_20261026/warm_greige_stone_basecolor_v1.png'
im=bpy.data.images.load(str(image_path),check_existing=True);im.colorspace_settings.name='sRGB';im.pack()
tex=n.new('ShaderNodeTexImage');tex.name='Pilot96_synthetic_albedo';tex.image=im;tex.extension='EXTEND';l.new(coord,tex.inputs['Vector'])
l.new(tex.outputs['Color'],n['R93_tile_colour_variation'].inputs[1])
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert sha(S)==before
(P/'views.json').write_text((D/'stone_material_pilot95/views.json').read_text())
(P/'scope.json').write_text(json.dumps({'source':str(S),'source_sha256':before,'candidate':str(out),'candidate_sha256':sha(out),'albedo':str(image_path),'albedo_sha256':sha(image_path),'geometry_lights_camera_world_unchanged':True,'actual_tile':obj.name,'baseline_render':'../stone_material_pilot95/baseline/actual_tile_patch.png','change':'Only BaseColor mineral input replaced with synthetic image, 2m physical sampling, per-tile nonwrapping crop. Existing roughness and80um micro-normal unchanged.','photorealism_accepted':False,'limitations':'One diagnostic actual tile only; synthetic albedo1254square, not scanned PBR; no room or reference acceptance.'},indent=2))
