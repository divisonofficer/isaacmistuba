"""CPU A/B/C and geometry diagnostic, shared exact camera/render settings."""
import json,subprocess,os,datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';out=ref/'breakout_diagnostics_r28';out.mkdir(exist_ok=True);state=out/'job.json';assert not state.exists();views=[v for v in json.loads((base/'review_views_delivery_r23.json').read_text()) if v['name']=='breakout_kitchen']
for v in views:v['render_width']=1024;v['samples']=48
vf=out/'views.json';vf.write_text(json.dumps(views,indent=2));d={'pid':os.getpid(),'phase':'rendering','device':'CPU','started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'completed':[],'variants':{'A':'r27 unmodified','B':'only side80Warea light added','C':'only local scanned oak/fabric alternative','G':'only chair/cabinet geometry corrected'}};state.write_text(json.dumps(d,indent=2));env=dict(os.environ,CUDA_VISIBLE_DEVICES='')
try:
 for variant,source in [('A',base/'scene_candidate_r27.blend'),('B',base/'breakout_diagnostic_r28B.blend'),('C',base/'breakout_diagnostic_r28C.blend'),('G',base/'scene_candidate_r28.blend')]:
  assert source.exists(),source
  cmd=['python3',str(ROOT/'tools/infinigen/run_bundled_blender.py'),'-t','8','--background',str(source),'--python-exit-code','1','--python',str(Path(__file__).with_name('render.py')),'--','--views',str(vf),'--out',str(out/variant),'--width','1024','--samples','48']
  with (out/(variant+'.log')).open('w') as f:subprocess.run(cmd,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
  d['completed'].append(variant);state.write_text(json.dumps(d,indent=2))
 d['phase']='rendered_visual_review_pending'
except Exception as exc:d['phase']='failed';d['error']=str(exc);raise
finally:d['updated_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();state.write_text(json.dumps(d,indent=2))
