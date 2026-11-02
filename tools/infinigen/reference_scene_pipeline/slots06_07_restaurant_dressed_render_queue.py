import json,time,subprocess,os
from pathlib import Path
R=Path(__file__).resolve().parents[3];W=R/'out/infinigen_v2/kr_large_restaurant_floor_07_48712507';receipt=W/'render_queue_r5.json';prior=R/'out/infinigen_v2/kr_industrial_workshop_floor_06_48712506/review_r2_full/job.json';state={'pid':os.getpid(),'phase':'waiting_for_owned_workshop_render','prior':str(prior),'device':'CPU','threads':2}
def save():receipt.write_text(json.dumps(state,indent=2))
save()
while True:
 p=json.loads(prior.read_text())
 if 'exit_code' in p or p.get('phase')=='failed':break
 time.sleep(5)
cmd=['python3',str(R/'tools/infinigen/reference_scene_pipeline/run_observed_render.py'),'--blend',str(W/'furnished_r5.blend'),'--views',str(W/'furnished_r5_views.json'),'--out',str(W/'review_r5/frames'),'--samples','16','--threads','2','--preserve-source-lighting'];state.update(phase='rendering_restaurant_corrected',argv=cmd);save();c=subprocess.Popen(cmd,cwd=R);state['child_pid']=c.pid;save();state.update(exit_code=c.wait(),phase='finished');save()
