import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
root=Path('/jarvis/project/robomituba');src=root/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r90.blend';out=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/window_inventory_r90.json'
assert not out.exists()
def sha():
 h=hashlib.sha256()
 with src.open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
before=sha();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
for obj in bpy.context.scene.objects:
 if not any(w in obj.name.lower() for w in ['window','wall','room']):continue
 if obj.type not in ['MESH','EMPTY','LIGHT']:continue
 row={'name':obj.name,'type':obj.type,'parent':obj.parent.name if obj.parent else None,'hidden_render':obj.hide_render,'properties':{k:str(v)[:600] for k,v in obj.items()}}
 if obj.type=='MESH':
  pts=[obj.matrix_world@Vector(v) for v in obj.bound_box]
  row.update(bounds_min=[min(p[i] for p in pts) for i in range(3)],bounds_max=[max(p[i] for p in pts) for i in range(3)],faces=len(obj.data.polygons),materials=[m.name if m else None for m in obj.data.materials])
 rows.append(row)
assert sha()==before
out.write_text(json.dumps({'source':str(src),'source_sha256':before,'read_only':True,'scope':'Named window/wall/room source objects only. No claim exhaustive semantic openings, evaluated CSG or compliance. Bounds are object box, not true opening contours.','objects':rows},indent=2));print('INVENTORY_WRITTEN',len(rows),flush=True)
