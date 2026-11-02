"""Fresh factory regression against actual pre-fix mesh footprint,not approximate doc dimensions."""
import bpy,sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path[:0]=[str(ROOT/'tools/infinigen'),str(ROOT/'modules/infinigen')]
from room_planner.proc_home import SectionalSofaFactory
ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';before=json.loads((ref/'sofa_component_probe_r46.json').read_text())['objects'][0]['components'];expected_xy=[max(c['bounds'][1][k] for c in before)-min(c['bounds'][0][k] for c in before) for k in [0,1]];bpy.ops.wm.read_factory_settings(use_empty=True);o=SectionalSofaFactory(48712503).spawn_asset(48712503);m=o.data;adj=[[] for _ in m.vertices]
for e in m.edges:a,b=e.vertices;adj[a].append(b);adj[b].append(a)
pending=set(range(len(m.vertices)));backs=[]
while pending:
 stack=[pending.pop()];ids=[]
 while stack:
  i=stack.pop();ids.append(i)
  for j in adj[i]:
   if j in pending:pending.remove(j);stack.append(j)
 pts=[m.vertices[i].co for i in ids];lo=[min(p[k] for p in pts) for k in range(3)];hi=[max(p[k] for p in pts) for k in range(3)]
 if abs(lo[0]-.01)<1e-5 and abs(hi[0]-.27)<1e-5 and lo[2]>.35 and hi[2]>.87:backs.append([lo,hi])
assert len(backs)==1 and backs[0][0][1]<-1.59 and backs[0][1][1]>1.59
xy=[max(v.co[k] for v in m.vertices)-min(v.co[k] for v in m.vertices) for k in [0,1]];assert all(abs(xy[k]-expected_xy[k])<1e-5 for k in [0,1]);d={'bpy_version':bpy.app.version_string,'factory':'SectionalSofaFactory','back_components':len(backs),'back_bounds':backs,'footprint_xy_m':xy,'before_footprint_xy_m':expected_xy,'footprint_unchanged':True,'test_note':'Initial smoke assumed approximate documented1.9m depth and failed:actual old chaise cushion footprint is2.04m. Corrected assertion compares measured pre-fix source mesh;factory geometry was not changed to satisfy that test.','scope':'Fresh factory geometry regression;not photo/all-collision acceptance'};(ref/'sectional_factory_validation.json').write_text(json.dumps(d,indent=2));print(json.dumps(d),flush=True)
