import bpy,json,math
from pathlib import Path
from collections import Counter
r=Path(__file__).resolve().parents[3];bpy.ops.wm.open_mainfile(filepath=str(r/'data/plant_library_v2/spiderplant_002.blend'));o=bpy.data.objects['ir_plant'];vs=[o.matrix_world@v.co for v in o.data.vertices];hist=Counter(round(v.z/.005)*.005 for v in vs if math.hypot(v.x,v.y)<.04);out={'canonical_bbox_center_lowest_origin':True,'central_vertex_z_histogram':sorted(hist.items()),'mode_z_m':hist.most_common(1)[0][0]};p=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/botanical114_products/origin_probe.json';p.write_text(json.dumps(out,indent=2));print(json.dumps(out))
