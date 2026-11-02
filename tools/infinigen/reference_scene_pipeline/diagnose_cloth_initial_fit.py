"""Native shoulder dimensions vs fixed hanger; inspect initial state before spending another solve."""
import os,json,math
from pathlib import Path
path=Path(__file__).with_name('settle_garments_on_hangers_r41.py');code=path.read_text().split('for frame in range(1,61):')[0];code=code.replace('assert not out.exists();','').replace('range(6)','range(1)').replace("state=ref/'hanger_settlement_r41_job.json'","state=ref/'native_shoulder_fit_preflight_job.json'")
code=code.replace('scale=min(1,.47/(bounds[0][1]-bounds[0][0]),.59/(bounds[2][1]-bounds[2][0]))','scale=min(1,.59/(bounds[2][1]-bounds[2][0]))').replace('*(.0022+.0015)','*(.0022+.0027)')
tag=os.environ.get('SHOULDER_CLEARANCE','004')
code=code.replace('wire_z+.004','wire_z+'+str(float(tag)/1000)).replace("'native_shoulder_fit_preflight_job.json'",repr('native_shoulder_fit_'+tag+'_job.json'))
exec(compile(code,str(path),'exec'))
proto=prototypes[0];points=[v.co-origins[0] for v in proto.data.vertices];tree=BVHTree.FromPolygons(points,[list(f.vertices) for f in proto.data.polygons]);rows=[]
for a,b in [((-.18,0,-.075),(0,0,0)),((0,0,0),(.18,0,-.075)),((.18,0,-.075),(-.18,0,-.075))]:
 a,b=Vector(a),Vector(b);n=math.ceil((b-a).length/.0005);minimum=min(tree.find_nearest(a.lerp(b,k/n))[3] for k in range(n+1));rows.append({'minimum_body_surface_to_wire_centerline_m':minimum,'penetration_demonstrated':minimum<.0022})
result={'scope':'No cloth steps;fresh native pattern0,only height fit cap59cm,2.7mm support pin clearance;actual initial body triangles vs real wire segments.','initial_top_above_wire_centerline_m':float(tag)/1000,'native_width_m':.4,'fixed_wire_shoulder_span_m':.36,'body_bounds':[[min(p[k] for p in points) for k in range(3)],[max(p[k] for p in points) for k in range(3)]],'segments':rows,'pins':json.loads(proto['contact_pin_proof_json']),'photo_acceptance':False};(ref/('native_shoulder_fit_'+tag+'.json')).write_text(json.dumps(result,indent=2));print('INITIAL_NATIVE_FIT',json.dumps(result),flush=True)
