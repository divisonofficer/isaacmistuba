"""One render job at a time, CPU2, preserved candidate files and durable receipts."""
import subprocess,sys,os,json,time,traceback
from pathlib import Path
R=Path(__file__).resolve().parents[3];T=Path(__file__).parent;D=R/'data/venue_refs/floor_plans_v3';receipt=D/'skyline_penthouse_08/render_queue_r002.json';state={'pid':os.getpid(),'device':'CPU','threads':2,'phase':'starting','jobs':[]};receipt.write_text(json.dumps(state,indent=2))
try:
 for scene,seed in [('double_height_duplex_09',48712509),('skyline_penthouse_08',48712508)]:
  d=D/scene;b=R/'out/infinigen_v2'/f'kr_{scene}_{seed}/full/scene_candidate_r002.blend'
  while not b.exists():
   j=d/'build_r002_job.json'
   if j.exists() and json.loads(j.read_text()).get('phase')=='failed':raise RuntimeError(str(j))
   time.sleep(3)
  out=d/'render_r002/frames';cmd=['python3',str(T/'run_observed_render.py'),'--blend',str(b),'--views',str(d/'views_r002.json'),'--out',str(out),'--threads','2','--samples','32','--preserve-source-lighting'];job={'scene_id':scene,'phase':'live','started_unix':time.time()};state['jobs'].append(job);state['phase']='rendering'
  with (d/'render_r002_manager.log').open('w') as f:
   p=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT,env={**os.environ,'CUDA_VISIBLE_DEVICES':'','OMP_NUM_THREADS':'2','OPENBLAS_NUM_THREADS':'2'});job['pid']=p.pid;receipt.write_text(json.dumps(state,indent=2));code=p.wait()
  job.update(phase='rendered_review_pending' if code==0 else 'failed',exit_code=code,finished_unix=time.time());receipt.write_text(json.dumps(state,indent=2))
 state['phase']='finished';receipt.write_text(json.dumps(state,indent=2))
except BaseException as e:state.update(phase='failed',error=repr(e),traceback=traceback.format_exc());receipt.write_text(json.dumps(state,indent=2));raise
