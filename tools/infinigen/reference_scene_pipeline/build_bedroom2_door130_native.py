"""Actual single-leaf native Infinigen door sized for measured910mm bedroom apertures."""
import bpy,json,sys
from pathlib import Path
from mathutils import Vector
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(r/'modules/infinigen'));from infinigen.assets.objects.elements.doors.base import BaseDoorFactory
D=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/native_bedroom2_door130';D.mkdir(exist_ok=True);dst=D/'native_asset.blend';assert not dst.exists();src=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r129_draft.blend';bpy.ops.wm.read_factory_settings(use_empty=True)
with bpy.data.libraries.load(str(src),link=False) as (available,loaded):loaded.materials=['res03_oak']
body=loaded.materials[0];assert body;metal=bpy.data.materials.new('Door130_satin_steel');metal.use_nodes=True;bs=metal.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(.48,.5,.52,1);bs.inputs['Metallic'].default_value=1;bs.inputs['Roughness'].default_value=.26;bs.inputs['IOR'].default_value=1.5
class Surface:
 def __init__(self,material):self.material=material
 def apply(self,objects,**kwargs):
  for o in objects if isinstance(objects,(tuple,list)) else [objects]:
   if o is not None:o.data.materials.clear();o.data.materials.append(self.material)
fac=BaseDoorFactory(48712503);fac.width=.82;fac.height=2.3;fac.depth=.045;fac.door_frame_width=.04;fac.has_glass=False;fac.has_louver=False;fac.handle_type='lever';fac.handle_joint='hinge';fac.handle_info_dict={'handle_type':'lever'};fac.door_frame_style='full_frame_square';fac.door_orientation='left';fac.level_type='cylinder';fac.side_bevel=.0015;fac.auto_bevel.amount=.001;fac.surface=Surface(body);fac.handle_surface=Surface(metal);fac.handle_height=1.05;fac.handle_offset=.055
o=fac.create_asset(apply=True);o.name='Residential130_native_single_leaf_frame_lever';bpy.context.view_layer.update();used={i for f in o.data.polygons for i in f.vertices};rows=[]
for name in ['door_frame','door','door_left','handle']:
 a=o.data.attributes.get(name)
 if not a or a.domain!='POINT':continue
 ids=[i for i in used if a.data[i].value];ps=[o.matrix_world@o.data.vertices[i].co for i in ids];rows.append({'part':name,'faced_vertices':len(ids),'bbox_m':[[min(p[k] for p in ps) for k in range(3)],[max(p[k] for p in ps) for k in range(3)]] if ps else None})
bpy.ops.wm.save_as_mainfile(filepath=str(dst));(D/'native_contract.json').write_text(json.dumps({'source_factory':'infinigen.assets.objects.elements.doors.base.BaseDoorFactory','seed':48712503,'requested_leaf_width_height_depth_m':[.82,2.3,.045],'frame_profile_width_m':.04,'object':o.name,'polygons':len(o.data.polygons),'hardware_polygons':sum(o.data.materials[f.material_index]==metal for f in o.data.polygons),'parts':rows,'post_generation_rescaling':False,'accepted':False,'scope':'Actual generated native single-leaf square frame/lever. Not installed, no support/fit/sweep/material realism acceptance.'},indent=2));print('NATIVE130_DOOR',rows,flush=True)
