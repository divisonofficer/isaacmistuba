import bpy,json
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';a=json.loads((d/'private_windows114_source_probe.json').read_text());bpy.ops.wm.open_mainfile(filepath=a['source']);rows=[]
for o in bpy.context.scene.objects:
 if o.type!='MESH':continue
 vs=[o.matrix_world@Vector(p) for p in o.bound_box]
 if min(v.x for v in vs)>1.2 or max(v.y for v in vs)<3 or min(v.y for v in vs)>18 or max(v.z for v in vs)<2.5:continue
 tree=BVHTree.FromPolygons([o.matrix_world@v.co for v in o.data.vertices],[list(f.vertices) for f in o.data.polygons]);hits=[]
 for y in [3.3,5.2,5.8,7.7,8.3,10.2,10.8,12.7,13.3,15.2,15.8,17.7]:
  loc,n,idx,dist=tree.ray_cast(Vector((-1,y,2.5)),Vector((1,0,0)),2.1)
  if loc:hits.append([y,list(loc)])
 if hits:rows.append({'object':o.name,'program_key':str(o.get('program_key','')),'hits':hits})
(d/'private114_shell_layers.json').write_text(json.dumps(rows,indent=2));print(json.dumps(rows))
