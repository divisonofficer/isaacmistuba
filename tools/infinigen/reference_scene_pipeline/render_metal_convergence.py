"""Same source/cameras/exposure/denoising, increased samples to test apparent melted metal."""
import os,subprocess,json,datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';out=ref/'convergence_r35';out.mkdir(exist_ok=True);state=out/'job.json';assert not state.exists();views=[v for v in json.loads((ref/'breakout_r35/views.json').read_text()) if v['name'] in ['breakout_sink_detail','coffee_machine_detail']]
for v in views:v['samples']=192
vf=out/'views.json';vf.write_text(json.dumps(views,indent=2));d={'pid':os.getpid(),'phase':'rendering','device':'CPU','threads':16,'samples':192,'baseline_samples':48,'source_revision':35,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'unchanged source/camera/exposure/denoising;sample convergence only'};state.write_text(json.dumps(d,indent=2));cmd=['python3',str(ROOT/'tools/infinigen/run_bundled_blender.py'),'-t','16','--background',str(base/'scene_candidate_r35.blend'),'--python-exit-code','1','--python',str(Path(__file__).with_name('render.py')),'--','--views',str(vf),'--out',str(out/'candidate'),'--width','1280','--samples','192','--threads','16']
try:
 with (out/'render.log').open('w') as f:subprocess.run(cmd,cwd=ROOT,env=dict(os.environ,CUDA_VISIBLE_DEVICES=''),stdout=f,stderr=subprocess.STDOUT,check=True)
 d['phase']='rendered_visual_review_pending'
except Exception as e:d['phase']='failed';d['error']=str(e);raise
finally:d['updated_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();state.write_text(json.dumps(d,indent=2))
