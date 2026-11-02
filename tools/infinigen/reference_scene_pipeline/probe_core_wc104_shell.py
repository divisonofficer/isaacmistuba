import bpy,json,hashlib,sys
from pathlib import Path
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent))
from mathutils import Vector
def bounds(o):
 ev=o.evaluated_get(bpy.context.evaluated_depsgraph_get());pts=[ev.matrix_world@Vector(v) for v in ev.bound_box]
 return Vector(tuple(min(p[k] for p in pts) for k in range(3))),Vector(tuple(max(p[k] for p in pts) for k in range(3)))
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/core_wc104_planning';S=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r103.blend';h=hashlib.sha256(S.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(S));rows=[]
for o in bpy.context.scene.objects:
 if o.type!='MESH':continue
 lo,hi=bounds(o)
 intersects=lo.x<14.7 and hi.x>6.8 and lo.y<9.8 and hi.y>5.8
 if not intersects:continue
 shell=o.name.endswith(('.wall','.exterior','.floor','.ceiling')) or 'skirting' in o.name.lower()
 door='door' in o.name.lower() or 'casing' in o.name.lower()
 if not(shell or door):continue
 row={'name':o.name,'bbox_m':[list(lo),list(hi)],'program_key':o.get('program_key'),'vertices':len(o.data.vertices),'polygons':len(o.data.polygons),'materials':[m.name for m in o.data.materials if m],'matrix':[list(v) for v in o.matrix_world],'attributes':[(a.name,a.domain,a.data_type) for a in o.data.attributes]}
 if o.name in ['hallway_0/1.wall','hallway_0/4.wall','hallway_0/7.wall']:
  row['world_vertices']=[list(o.matrix_world@v.co) for v in o.data.vertices];row['faces']=[list(f.vertices) for f in o.data.polygons]
 rows.append(row)
assert hashlib.sha256(S.read_bytes()).hexdigest()==h
(D/'source_shell_inventory.json').write_text(json.dumps({'source':str(S),'sha256':h,'rows':rows},indent=2));print('CORE_SHELL_INVENTORY',len(rows),flush=True)
