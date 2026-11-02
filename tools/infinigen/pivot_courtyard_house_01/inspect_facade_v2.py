import bpy,json
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];s=bpy.context.scene
# Inspect along kitchen window into interior, excluding glass only for diagnostic.
windows=[o for o in bpy.data.objects if o.name.startswith('PivotLayoutV2_courtyard') and 'glass' in o.name]
for o in windows:o.hide_set(True)
bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();rows=[]
for y in [4.6,5.8,7.1,8.4]:
 origin=Vector((15.8,y,1.4));hit,co,no,f,o,m=s.ray_cast(dg,origin,Vector((1,0,0)))
 rows.append({'y':y,'hit':hit,'object':o.name if o else None,'point':list(co)})
for o in windows:o.hide_set(False)
(R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01/facade_diagnostic_v2.json').write_text(json.dumps(rows,indent=2));print('FACADE_DIAGNOSTIC_V2',rows,flush=True)
