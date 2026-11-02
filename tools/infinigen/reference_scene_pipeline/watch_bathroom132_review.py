"""Refresh local A/B evidence; never starts or restarts a renderer."""
import json,time,os,subprocess,datetime
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=D/'bathroom_door132_review';state={'pid':os.getpid(),'phase':'live','started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
while True:
 p=subprocess.run(['python3',str(Path(__file__).with_name('report_bathroom132.py'))],cwd=R,capture_output=True,text=True)
 state.update(last_refresh_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),report_exit_code=p.returncode,last_output=p.stdout[-1000:],last_error=p.stderr[-1000:])
 if p.returncode:state['phase']='report_failed'
 else:
  a=json.loads((out/'evidence.json').read_text())
  if a['completed_pairs']==2:state['phase']='rendered_direct_visual_review_pending'
  elif any(j.get('phase')=='failed' for j in a['jobs']):state['phase']='render_failed'
 (out/'watcher.json').write_text(json.dumps(state,indent=2))
 if state['phase']!='live':break
 time.sleep(30)
