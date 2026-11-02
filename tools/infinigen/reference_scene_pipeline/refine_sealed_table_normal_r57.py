"""Reduce raw open-grain relief for the sealed tabletop, retaining scanned colour/roughness."""
import bpy,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
src=base/'scene_candidate_r53.blend';out=base/'scene_candidate_r57.blend'
assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src))
table=next(o for o in bpy.data.objects if o.get('program_key')=='breakout_table')
slot=next(s for s in table.material_slots if s.material and s.material.name=='R53_table_scan_oak')
m=slot.material.copy();m.name='R57_sealed_table_relief';slot.material=m;rows=[]
for n in m.node_tree.nodes:
 if n.type=='NORMAL_MAP':
  assert not n.inputs['Strength'].is_linked
  before=n.inputs['Strength'].default_value;n.inputs['Strength'].default_value=.16;rows.append({'node':n.name,'before':before,'after':.16})
assert len(rows)==1
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
(ref/'realism_refinement_r57.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'trigger':'Actual close view shows strong comb-like tabletop grain relief versus sealed reference timber','scope':'Table scan normal strength only;colour,roughness,coat,micro bump,geometry and lighting unchanged','changes':rows,'photorealism_accepted':False,'requires':'Same actual close view andwide if locally improved; reject flat plastic finish or grain disappearance'},indent=2))
print('SAVED',out,flush=True)
