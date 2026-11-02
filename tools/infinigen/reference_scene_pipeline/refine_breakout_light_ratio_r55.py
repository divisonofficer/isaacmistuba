"""Window/practical power-ratio trial; preserve baseline runtime policy explicitly."""
import bpy,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
src=base/'scene_candidate_r53.blend';out=base/'scene_candidate_r55.blend'
assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest()
bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
# Bake only the existing legacy runtime energy overrides for reproducible authored rendering.
for o in bpy.data.objects:
 if o.type=='LIGHT' and o.data.type=='AREA' and o.parent and 'Window' in o.parent.name:
  o.data=o.data.copy();area=o.data.size*(o.data.size_y if o.data.shape=='RECTANGLE' else o.data.size);o.data.energy=65*max(area,.1)
bg=bpy.context.scene.world.node_tree.nodes.get('Background')
if bg:bg.inputs['Strength'].default_value=.45
for name,power in [('office02_area.002',70),('office02_area.003',70),('Area.001',260),('Area.002',130),('Area.003',130)]:
 o=bpy.data.objects[name];before=o.data.energy;o.data=o.data.copy();o.data.energy=power;rows.append({'object':name,'baseline_runtime_power':before,'trial_power':power})
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
(ref/'realism_refinement_r55.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'scope':'Five light powers only relative to53 legacy render; baseline runtime overrides baked for authored mode. Geometry,materials,world active shader,cameras and exposure unchanged','changes':rows,'render_requirement':'--preserve-source-lighting, otherwise window powers overwritten','photorealism_accepted':False,'requires':'Same-camera53/55 comparison: directional material/volume response, no gloomy exposure-only gain or clipped highlights'},indent=2))
print('SAVED',out,flush=True)
