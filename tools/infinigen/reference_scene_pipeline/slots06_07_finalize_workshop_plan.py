import json,sys
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/industrial_workshop_floor_06';W=R/'out/infinigen_v2/kr_industrial_workshop_floor_06_48712506';sys.path.insert(0,str(Path(__file__).parent));from preflight import audit
p=D/'floor_plan.json';backup=D/'floor_plan_reference_r0.json'
if not backup.exists():backup.write_bytes(p.read_bytes())
prev=D/'preflight_layout_reference_r0.json'
if not prev.exists():prev.write_bytes((D/'preflight_layout.json').read_bytes())
plan=json.loads(p.read_text())
for a in json.loads((W/'actual_openings_r2.json').read_text())['rows']:
 lo,_,hi,_=a['aperture_along_z_m'];axis=a['axis'];c=a['wall_boundary_coordinate_m'];coords=[(c,lo),(c,hi)]if axis==0 else[(lo,c),(hi,c)];plan['entrance'if a['group']=='entrance'else'opens'][a['key']]['shape']='shapely.LineString('+repr(coords)+')'
p.write_text(json.dumps(plan,indent=2));c=json.loads((D/'scene_contract.json').read_text());c['revision']='actual_native_apertures_r1';c['source_uncertainties'] += [x for x in ['External ground-floor south entry is inferred; original southcentral opening may be window. Reference central stair/service elevation and actual approach remain unresolved.','Current measured native entrance rough wall hole1.148678x2.388509m supersedes provisional2m planline; fresh native single leaf1.058678x2.332509m uses no post-generation scaling.']if x not in c['source_uncertainties']];(D/'scene_contract.json').write_text(json.dumps(c,indent=2));j=audit(D);assert j['status']=='pass';(D/'preflight_layout.json').write_text(json.dumps(j,indent=2));(D/'preflight_layout_r1.json').write_text(json.dumps(j,indent=2))
print('WORKSHOP_ACTUAL_PLAN_PREFLIGHT',j['status'],j['floor_plan_sha256'])
