"""Two authored finish gains over the same photographic native oak PBR, immutable source104."""
import bpy,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];D=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';S=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r104.blend';W=D/'wood_finish105_pilot';W.mkdir(exist_ok=True);sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();source_sha=sha(S);bpy.ops.wm.open_mainfile(filepath=str(S));mat=bpy.data.materials['Office02_r104_photographic_sealed_oak'];node=mat.node_tree.nodes['R104_preserved_linear_gain'];old=list(node.inputs[2].default_value)
# The only changed scene value is the finish's RGB linear diffuse multiplier.
rows=[]
for name,gain in [('warm_tan',(.52,.34,.20)),('deeper_oak',(.38,.24,.13))]:
 out=W/(name+'.blend');assert not out.exists();node.inputs[2].default_value=(*gain,1);bpy.ops.wm.save_as_mainfile(filepath=str(out));rows.append({'name':name,'source':str(out),'source_sha256':sha(out),'linear_gain':gain,'changed_node':node.name,'unchanged':'All geometry/transforms/bindings/UVs/native photographic roughness+GLnormal/coat/world/lights/cameras remain from104.'});print('SAVED_PILOT',name,flush=True)
assert sha(S)==source_sha;(W/'contract.json').write_text(json.dumps({'source':str(S),'source_sha256':source_sha,'old_gain':old,'pilots':rows,'scope':'Authored wood finish colour trial,not a new scanned material or calibrated reflectance. No room/reference/photorealism acceptance. No scene promotion.'},indent=2));receipt=json.load(open(D/'veneer_r104_photographic_screen/candidate/render_receipt.json'));(W/'views.json').write_text(json.dumps([f['camera'] for f in receipt['frames']],indent=2))
