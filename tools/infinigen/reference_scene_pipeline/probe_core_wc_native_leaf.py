import bpy,json
from pathlib import Path
R=Path(__file__).resolve().parents[3];S=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/native_flat_door_pilot02/asset.blend';bpy.ops.wm.open_mainfile(filepath=str(S));o=bpy.data.objects['Office02_native_flat_leaf_full_frame_lever'];rows=[]
for i,m in enumerate(o.data.materials):
 ids={v for f in o.data.polygons if f.material_index==i for v in f.vertices}
 if not ids:continue
 ps=[o.matrix_world@o.data.vertices[v].co for v in ids];rows.append({'slot':i,'material':m.name,'faces':sum(f.material_index==i for f in o.data.polygons),'bbox':[[min(p[k] for p in ps) for k in range(3)],[max(p[k] for p in ps) for k in range(3)]]})
print(json.dumps(rows),flush=True)
