"""Keep native neckline;choose highest central apex satisfying measured lip clearance,not solver tuning."""
from pathlib import Path
import json
path=Path(__file__).with_name('build_native_roof_hanger_pilot04.py');code=path.read_text().replace('garment_roof_hanger_pilot04','garment_roof_hanger_pilot08').replace("shirt.name='Untouched_native_shirt'","shirt.name='Native_neck_clearance_fit_shirt'").replace('untouched height-fitted native shirt','native neckline retained; height-fitted anddecimated shirt;measured collar-safe apex')
needle="exec(compile(code,str(p),'exec'))";replacement="start=code.index('\\n bm=bmesh.new();bm.from_mesh(f.data);remove=[]');stop=code.index('fresh.append(f)',start);code=code[:start]+'\\n fresh.append(f)'+code[stop+len('fresh.append(f)'):];exec(compile(code,str(p),'exec'))";assert code.count(needle)==1;code=code.replace(needle,replacement)
needle='wire=shoulders[0][::-1]+[Vector((0,0,.06))]+shoulders[1]';assert code.count(needle)==1
search='''
def segment_clearance(a,b):
 length=(b-a).length;n=max(1,math.ceil(length/.0005));return min(tree.find_nearest(a.lerp(b,k/n))[3] for k in range(n+1))-length/n/2
apex_search=[];apex_z=None
for mm in range(60,4,-1):
 z=mm/1000;apex=Vector((0,0,z));clearance=min(segment_clearance(shoulders[0][0],apex),segment_clearance(apex,shoulders[1][0]));apex_search.append({'apex_z_m':z,'lip_clearance_lower_bound_m':clearance})
 if clearance>=radius+.0015+.001+.0005:apex_z=z;break
assert apex_z is not None,('No positive-height apex meets measured lip clearance',apex_search)
wire=shoulders[0][::-1]+[Vector((0,0,apex_z))]+shoulders[1]'''
code=code.replace(needle,search);exec(compile(code,str(path),'exec'))
proof=json.loads((ref/'garment_roof_hanger_pilot08_preflight.json').read_text());proof.update(experiment='Native neckline retained;only central apex selected byactual nearest-surface clearance. Shoulder points/radius/gap/contact selection unchanged.',manual_neck_face_deletion=False,apex_z_m=apex_z,apex_search=apex_search,extra_initial_margin_m=.0005,room_integrated=False,photorealism_accepted=False,physics_solve_started=False);(ref/'garment_roof_hanger_pilot08_preflight.json').write_text(json.dumps(proof,indent=2));state=ref/'garment_roof_hanger_pilot08_job.json';d=json.loads(state.read_text());d.update(phase='initial_preflight_pass_not_settled',physics_solve_started=False,room_integrated=False);state.write_text(json.dumps(d,indent=2));print('COLLAR_APEX_INITIAL_PASS',apex_z,'not settled/not integrated',flush=True)
