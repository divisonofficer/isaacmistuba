"""Native manufactured glazing pilot; no source scene modified or accepted."""
import os,sys,json,hashlib
from pathlib import Path
import bpy
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'modules/infinigen'))
from infinigen.assets.objects.windows.window import WindowFactory
OUT=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/native_private_glazing114'
assert not OUT.exists();OUT.mkdir()
bpy.ops.wm.read_factory_settings(use_empty=True)
fac=WindowFactory(87430,curtain=False,shutter=False)
original_sample=fac.sample_asset_params
controlled={'PanelHAmount':1,'PanelVAmount':2,'SubPanelHAmount':1,'SubPanelVAmount':1,'FrameWidth':.045,'SubFrameWidth':.018,'SubFrameThickness':.06,'GlassThickness':.008}
def sample_controlled(*args,**kwargs):
 p=original_sample(*args,**kwargs);p.update(controlled);return p
fac.sample_asset_params=sample_controlled
o=fac.create_asset(dimensions=(2.1,2.35,.22),open=False)
o.name='Office02_native_private_glazing114'
bpy.context.view_layer.update()
def mat(name,color,rough,metal=0,transmission=0):
 m=bpy.data.materials.new(name);m.use_nodes=True;p=m.node_tree.nodes.get('Principled BSDF');p.inputs['Base Color'].default_value=(*color,1);p.inputs['Roughness'].default_value=rough;p.inputs['Metallic'].default_value=metal;p.inputs['Transmission Weight'].default_value=transmission;p.inputs['IOR'].default_value=1.5;return m
frame=mat('Pilot_black_powder_coat',(.018,.022,.026),.32)
glass=mat('Pilot_clear_dielectric_no_camera_branch',(.99,.995,1),.015,transmission=1)
oldglass=fac.params['Material'];oldframe=fac.params['FrameMaterial'];assign=[]
for i,m in enumerate(o.data.materials):
 if m==oldglass:o.data.materials[i]=glass;assign.append({'slot':i,'from':m.name,'to':glass.name})
 elif m==oldframe:o.data.materials[i]=frame;assign.append({'slot':i,'from':m.name,'to':frame.name})
assert any(x['to']==glass.name for x in assign) and any(x['to']==frame.name for x in assign)
# Native portal has no emitted power; do not add unexplained lights to final asset.
for child in list(o.children):
 if child.type=='LIGHT':bpy.data.objects.remove(child,do_unlink=True)
pts=[o.matrix_world@Vector(v) for v in o.bound_box];o.location.z-=min(v.z for v in pts)
bpy.context.view_layer.update()
asset=OUT/'asset.blend';bpy.ops.wm.save_as_mainfile(filepath=str(asset))
(OUT/'provenance.json').write_text(json.dumps({'factory':'infinigen.assets.objects.windows.window.WindowFactory','seed':87430,'controlled_native_parameters':controlled,'dimensions_requested_m':[2.1,2.35,.22],'dimensions_actual_m':list(o.dimensions),'faces':len(o.data.polygons),'vertices':len(o.data.vertices),'material_replacements':assign,'asset_sha256':hashlib.sha256(asset.read_bytes()).hexdigest(),'scope':'Native manufactured window pilot only. Frame cross-sections, pane thickness, topology, room fit and actual RGB require inspection before integration. No source scene altered.','photorealism_accepted':False},indent=2)+'\n');print('NATIVE_GLAZING_PILOT_SAVED',flush=True)
