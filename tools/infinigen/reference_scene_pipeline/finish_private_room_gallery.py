"""Observe one existing CPU job and publish its completed source-bound gallery.
Does not restart/stop renders. Missing or inconclusive process state is not exit.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
D=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/all_private_offices_r102'
status=D/'gallery_update_job.json'
started=time.time()
record={'pid':os.getpid(),'phase':'observing_existing_render','render_job':str(D/'job.json')}
status.write_text(json.dumps(record,indent=2))
while time.time()-started<7200:
    try:
        job=json.loads((D/'job.json').read_text())
    except (FileNotFoundError,json.JSONDecodeError):
        time.sleep(3)
        continue
    if job.get('exit_code') is not None:
        if job['exit_code'] != 0:
            record.update(phase='render_failed_gallery_not_updated',render_exit_code=job['exit_code'])
            break
        receipt=D/'candidate/render_receipt.json'
        if not receipt.exists():
            record.update(phase='render_terminal_receipt_missing')
            break
        command=[sys.executable,str(Path(__file__).with_name('report_all_room_renders.py'))]
        result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
        record.update(phase='gallery_updated' if result.returncode==0 else 'gallery_update_failed',
                      exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr)
        break
    # Observe liveness for evidence only; never infer terminal from kill(0) failure.
    try:
        os.kill(job['child_pid'],0)
        record['last_verified_live_unix']=time.time()
    except (KeyError,ProcessLookupError,PermissionError):
        record['last_observation']='unverifiable;waiting for authoritative job exit receipt'
    status.write_text(json.dumps(record,indent=2))
    time.sleep(5)
else:
    record.update(phase='observation_deadline_render_status_unresolved')
record['finished_unix']=time.time()
status.write_text(json.dumps(record,indent=2))
