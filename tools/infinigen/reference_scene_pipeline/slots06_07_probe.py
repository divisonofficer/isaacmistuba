import bpy,json
from pathlib import Path
R=Path(__file__).resolve().parents[3]
for s,z in [('industrial_workshop_floor_06',48712506),('large_restaurant_floor_07',48712507)]:
 p=R/'out/infinigen_v2'/f'kr_{s}_{z}'/'full/scene.blend';bpy.ops.wm.open_mainfile(filepath=str(p));rows=[{'name':o.name,'location':list(o.location),'dimensions':list(o.dimensions),'bounds_z':[min((o.matrix_world@v.co).z for v in o.data.vertices),max((o.matrix_world@v.co).z for v in o.data.vertices)]} for o in bpy.data.objects if o.type=='MESH' and any(t in o.name.lower() for t in ['floor','ceiling'])];(p.parent.parent/'shell_mesh_probe.json').write_text(json.dumps(rows,indent=2));print(s,rows[:8])
