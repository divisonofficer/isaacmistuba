"""Read saved native light flags; no claims from name-based renderer policy alone."""
import bpy,json
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';O=D/'glazing_proxy_light_comparison_r92.json';assert not O.exists();rows=[]
for rev in [88,92]:
 S=R/f'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r{rev}.blend';bpy.ops.wm.open_mainfile(filepath=str(S));lights=[]
 for o in bpy.context.scene.objects:
  if o.type!='LIGHT' or not o.parent:continue
  if not ('Window' in o.parent.name or 'east_glazing' in o.parent.name):continue
  lights.append({'object':o.name,'parent':o.parent.name,'type':o.data.type,'energy':o.data.energy,'is_portal':getattr(o.data.cycles,'is_portal',None),'size':o.data.size,'size_y':o.data.size_y,'shape':o.data.shape,'hide_render':o.hide_render,'matrix_world':[list(v) for v in o.matrix_world]})
 rows.append({'revision':rev,'source':str(S),'lights':lights})
O.write_text(json.dumps({'rows':rows,'scope':'Saved native light flags/transforms, not final emitted radiance or room illumination proof.'},indent=2)+'\n');print('NATIVE_LIGHT_COMPARISON_WRITTEN',flush=True)
