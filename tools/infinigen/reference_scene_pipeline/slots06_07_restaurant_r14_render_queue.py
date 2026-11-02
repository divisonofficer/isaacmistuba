import json,time,subprocess,os
from pathlib import Path
R=Path(__file__).resolve().parents[3];W=R/'out/infinigen_v2/kr_large_restaurant_floor_07_48712507';receipt=W/'render_queue_r14.json';prior=W/'review_r13/job.json';state={'pid':os.getpid(),'phase':'waiting_for_owned_restaurant_render','prior':str(prior),'device':'CPU','threads':2}
def save():receipt.write_text(json.dumps(state,indent=2))
save()
while True:
 p=json.loads(prior.read_text())
 if 'exit_code' in p or p.get('phase')=='failed':break
 time.sleep(5)
subprocess.run(['python3',str(R/'tools/infinigen/reference_scene_pipeline/slots06_07_reports.py')],cwd=R,check=True)
D=R/'data/venue_refs/floor_plans_v3/large_restaurant_floor_07';(D/'progress_full_r13.html').write_bytes((D/'progress.html').read_bytes())
cmd=['python3',str(R/'tools/infinigen/reference_scene_pipeline/run_observed_render.py'),'--blend',str(W/'furnished_r14_south_program.blend'),'--views',str(W/'furnished_r14_south_program_views.json'),'--out',str(W/'review_r14/frames'),'--samples','16','--threads','2','--preserve-source-lighting'];state.update(phase='rendering_restaurant_local_south_program',argv=cmd);save();c=subprocess.Popen(cmd,cwd=R);state['child_pid']=c.pid;save();state.update(exit_code=c.wait(),phase='finished');save()
