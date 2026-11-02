"""Controlled neckline test: keep native neck instead of deleting full faces;no room integration."""
from pathlib import Path
import json
path=Path(__file__).with_name('build_native_roof_hanger_pilot04.py');code=path.read_text().replace('garment_roof_hanger_pilot04','garment_roof_hanger_pilot06').replace("shirt.name='Untouched_native_shirt'","shirt.name='Native_neck_retained_shirt'").replace('untouched height-fitted native shirt','native neckline retained; height-fitted anddecimated shirt')
needle="exec(compile(code,str(p),'exec'))"
replacement="start=code.index('\\n bm=bmesh.new();bm.from_mesh(f.data);remove=[]');stop=code.index('fresh.append(f)',start);code=code[:start]+'\\n fresh.append(f)'+code[stop+len('fresh.append(f)'):];exec(compile(code,str(p),'exec'))"
assert code.count(needle)==1;code=code.replace(needle,replacement);exec(compile(code,str(path),'exec'))
proof=json.loads((ref/'garment_roof_hanger_pilot06_preflight.json').read_text());proof.update(experiment='Native neckline retained;all manual whole-face neck deletion removed. Same height/decimation,wire radius/initial gap andcontact selection asfailed04.',manual_neck_face_deletion=False,room_integrated=False,photorealism_accepted=False);(ref/'garment_roof_hanger_pilot06_preflight.json').write_text(json.dumps(proof,indent=2));print('NATIVE_NECK_CONTROL_INITIAL_PASS;not settled/not integrated',flush=True)
