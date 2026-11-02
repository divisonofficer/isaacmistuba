"""Retain native floor geometry; restrain regular grout/knots and calibrate sealed-wood response."""
import bpy,json,hashlib,numpy as np
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';source=base/'scene_candidate_r37.blend';out=base/'scene_candidate_r38.blend';assert not out.exists();sha=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source));floor=bpy.data.objects['kitchen_0/0.floor']
def geometry_hash(o):
 a=np.empty(len(o.data.vertices)*3,dtype=np.float32);o.data.vertices.foreach_get('co',a);return hashlib.sha256(a.tobytes()).hexdigest()
before=geometry_hash(floor)
if floor.data.users>1:floor.data=floor.data.copy()
m=floor.data.materials[0].copy();m.name='BreakoutR38_native_sealed_oak_floor';floor.data.materials[0]=m;changes=[]
for n in m.node_tree.nodes:
 if n.type=='GROUP' and n.node_tree.name.startswith('brick_cutter'):
  values={'brick_width':1.6,'brick_height':.16,'shift':.33,'gab':.006,'brick_bevel':.025,'seed':83.0}
 elif n.type=='GROUP' and n.node_tree.name.startswith('wood_shader'):
  values={'min_spec':.35,'max_spec':.45,'min_roughness':.34,'max_roughness':.48,'coat_weight':.20,'coat_roughness':.22,'grains_grain_height':.00006,'flake_flake_opacity':.04,'flake_flake_height':.00001,'fibers_fiber_opacity':.25,'fibers_fiber_height':.00002,'knots_knot_opacity':.25,'knots_knot_height':.00012}
 else:values={}
 for key,value in values.items():
  socket=n.inputs.get(key);assert socket is not None and not socket.is_linked,(n.name,key);old=socket.default_value;socket.default_value=value;changes.append({'group':n.node_tree.name,'input':key,'old':old,'new':value})
 if n.type=='BSDF_DIFFUSE' and not n.inputs['Color'].is_linked:
  old=list(n.inputs['Color'].default_value);n.inputs['Color'].default_value=(.20,.13,.07,1);changes.append({'node':n.name,'input':'unlinked joint diffuse color','old':old,'new':[.20,.13,.07,1]})
assert len(changes)>=15;assert geometry_hash(floor)==before;bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(source.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r38.json').write_text(json.dumps({'source':str(source),'candidate':str(out),'source_sha256':sha,'trigger':'Independent r36: repeating knots,thin long parallel floor pattern and bright joints','change_scope':'kitchen native floor material copy only;original mesh/world/lighting untouched','unchanged_floor_coordinates_sha256':before,'native_controls':changes,'units_note':'Native group controls recorded verbatim;unknown extrusion/gap-unit semantics are not asserted as actual millimetres. Grout extrusion itself left unchanged.','photorealism_accepted':False,'requires':'same-view floor/grain/joint/reflection comparison before adoption'},indent=2));print('SAVED',out,'controls',len(changes),flush=True)
