"""Durable single render attempt; record actual child exit separately from observations."""
import subprocess,json,os,time
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/veneer_r105_coherent_screen_retry';D.mkdir(exist_ok=False);job={'pid':os.getpid(),'phase':'starting','prior_attempt':'Terminal143 before renderer created output; original Blender PID1057864 confirmed absent. Cause unproven, original log preserved.','source':str(R/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r105.blend'),'started_unix':time.time()};jp=D/'job.json'
def save():jp.write_text(json.dumps(job,indent=2))
command=['python3',str(R/'tools/infinigen/run_bundled_blender.py'),'-t','8','--background','--python-exit-code','1','--python',str(R/'tools/infinigen/reference_scene_pipeline/render_with_load_receipt.py'),'--','--blend',job['source'],'--launch-report',str(D/'load.json'),'--views',str(R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/wood_finish105_pilot/views.json'),'--out',str(D/'candidate'),'--device','CPU','--threads','8','--samples','16'];job['command']=command;save()
with (D/'render.log').open('w') as f:
 child=subprocess.Popen(command,cwd=R,env={**os.environ,'CUDA_VISIBLE_DEVICES':''},stdout=f,stderr=subprocess.STDOUT);job.update(phase='live',child_pid=child.pid);save();code=child.wait()
job.update(phase='rendered_visual_review_pending' if code==0 else 'failed',exit_code=code,finished_unix=time.time());save();raise SystemExit(code)
