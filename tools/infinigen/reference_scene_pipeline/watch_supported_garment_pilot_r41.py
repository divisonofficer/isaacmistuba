"""Render only after the existing authoritative build has positively saved its candidate."""
import os,time,json,subprocess,datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';state=ref/'hanger_settlement_r41_job.json';receipt=ref/'garment_pilot_r41_watch.json';candidate=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r41.blend'
def record(phase,**extra):receipt.write_text(json.dumps({'pid':os.getpid(),'build_pid':1882411,'phase':phase,'updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),**extra},indent=2))
record('waiting_for_existing_build')
while True:
 d=json.loads(state.read_text())
 if d.get('phase')=='supported_prototypes_baked' and candidate.is_file() and (ref/'realism_refinement_r41.json').is_file():break
 try:os.kill(1882411,0)
 except ProcessLookupError:record('build_exited_without_success');raise SystemExit(1)
 time.sleep(10)
if (ref/'garment_pilot_r41/job.json').exists():record('existing_pilot_job_preserved');raise SystemExit(0)
record('rendering_pilot')
result=subprocess.run(['python3',str(Path(__file__).with_name('render_garment_pilot.py')),'--revision','41'],cwd=ROOT,env={**os.environ,'CUDA_VISIBLE_DEVICES':''})
record('pilot_rendered_review_pending' if result.returncode==0 else 'pilot_failed',returncode=result.returncode)
