"""Normal-only response comparison: retain single albedo,geometry,roughness and lighting."""
import bpy,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r44.blend';out=base/'scene_candidate_r45.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
for name in ['ir_sec_fabric','ir_sec_cushion','ir_sec_pillow_c','ir_sec_pillow_t']:
 m=bpy.data.materials[name]
 for n in m.node_tree.nodes:
  if n.type=='VECT_MATH' and n.operation=='SCALE' and not n.inputs[3].is_linked and abs(n.inputs[3].default_value-.18)<1e-5:
   n.inputs[3].default_value=1.0;rows.append({'material':name,'node':n.name,'old_scan_normal_strength':.18,'new_scan_normal_strength':1.0})
assert len(rows)==12;bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r45.json').write_text(json.dumps({'source':str(src),'candidate':str(out),'source_sha256':sha,'trigger':'43single albedo removes engraving but attenuated normal loses fibre response.','scope':'12triplanar normal perturbation strength nodes on4sofa textile materials;no dirt/noise added. Geometry,albedo,roughness,lighting,exposure unchanged.','changes':rows,'units_note':'Relative scan-normal strength,not asserted physical height in millimetres.','photorealism_accepted':False,'requires':'same-camera44/45normal-only visual comparison;stronger normal must not produce foil or pebble appearance'},indent=2));print('SAVED',out,flush=True)
