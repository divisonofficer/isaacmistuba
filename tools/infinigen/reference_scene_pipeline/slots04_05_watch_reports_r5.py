import json,os,subprocess,time
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/shared_dining_residence_05';receipt=D/'slots04_05_report_watch_r5.json';assert not receipt.exists();s={'pid':os.getpid(),'phase':'watching_cpu_queues','started_unix':time.time(),'scope':'Updates owned per-scene patches and external JPEG previews; never launches renders or edits candidates'}
def save():receipt.write_text(json.dumps(s,indent=2))
save()
with (D/'slots04_05_report_watch_r5.log').open('w') as log:
 while True:
  code=subprocess.call(['python3',str(R/'tools/infinigen/reference_scene_pipeline/slots04_05_report.py')],cwd=R,stdout=log,stderr=subprocess.STDOUT);s.update(last_refresh_unix=time.time(),last_exit_code=code);save();q=json.loads((D/'slots04_05_r5_cpu_queue.json').read_text())
  if q['phase']=='finished':break
  time.sleep(20)
s.update(phase='finished',finished_unix=time.time());save()
