"""Refresh the pinned final-review gallery while its original observed render runs."""
import json,os,time,subprocess,sys,datetime
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';p=D/'finalization/gallery_watcher.json';assert not p.exists(),'Do not duplicate an existing watcher';state={'pid':os.getpid(),'phase':'live','source_revision':130,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
def save():p.write_text(json.dumps(state,indent=2))
save()
while True:
 result=subprocess.run([sys.executable,str(Path(__file__).with_name('report_residential_finalization.py'))],cwd=R,capture_output=True,text=True);state.update(last_refresh_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),report_exit_code=result.returncode,last_output=result.stdout[-1000:],last_error=result.stderr[-1000:]);save()
 if result.returncode:state['phase']='report_error';save();break
 status=json.loads((D/'finalization/status.json').read_text());job=json.loads((D/'final_audit_r130_cpu/job.json').read_text())
 if status['complete_render_receipt']:state['phase']='all_frames_ready_review_pending';save();break
 if job['phase']=='failed':state['phase']='render_failed';save();break
 # Missing observation is recorded, not treated as process failure or authorization to restart.
 time.sleep(30)
