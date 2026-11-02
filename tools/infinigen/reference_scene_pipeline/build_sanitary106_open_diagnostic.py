"""Hide complete seat/lid assembly for cavity inspection only; never integrate this state."""
import bpy,json
from pathlib import Path
root=Path(__file__).resolve().parents[3];p=root/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/sanitary106_complete_products';out=p/'cavity_diagnostic.blend';assert not out.exists()
bpy.ops.wm.open_mainfile(filepath=str(p/'review_studio.blend'))
hidden=[]
for o in bpy.data.objects:
 if o.type=='MESH' and any(k in o.get('original_asset_id','') for k in ['0c4ab4','7ff8c2']) and o.name.endswith('.001'):
  o.hide_render=True;hidden.append(o.name)
assert len(hidden)==2
views=[v for v in json.loads((p/'review_views.json').read_text()) if v['name'].endswith('_outlet_top') and any(k in v['name'] for k in ['0c4ab4','7ff8c2'])]
for v in views:v['name']=v['name'].replace('_outlet_top','_cavity_no_seat');v['render_width']=1600;v['samples']=64
(p/'cavity_views.json').write_text(json.dumps(views,indent=2));(p/'cavity_scope.json').write_text(json.dumps({'hidden':hidden,'purpose':'Inspect bare ceramic bowl; seat/lid assembly hidden together, not a valid finished product state','integrated':False},indent=2));bpy.ops.wm.save_as_mainfile(filepath=str(out))
