"""Generate architecture only after plan preflight. CPU; no external LLM API."""
import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'scripts'))
from infinigen_gen import parse_seed,build_command
from preflight import audit

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('scene');ap.add_argument('--seed',type=int,required=True)
    args=ap.parse_args()
    if args.scene not in ('commercial_office_floor_02','dual_unit_residential_floor_03'):
        raise SystemExit('Only new slots allowed; approved PH is out of scope')
    ref=ROOT/'data/venue_refs/floor_plans_v3'/args.scene
    checked=audit(ref)
    (ref/'preflight_layout.json').write_text(json.dumps(checked,indent=2))
    if checked['status']!='pass':raise SystemExit('Plan preflight failed')
    work=ROOT/'out/infinigen_v2'/f'kr_{args.scene}_{args.seed}'
    full=work/'full';full.mkdir(parents=True,exist_ok=True)
    if (full/'scene.blend').exists():raise SystemExit('Existing scene preserved; explicit new candidate required')
    preset=parse_seed(args.seed);preset.floor_plan_key='reference_authored'
    cmd=build_command(preset,out=full,stage='full',fast=False,
        floor_plan_json=ref/'floor_plan.json',base_config='vanilla',small_objects='activity',
        extra_overrides=['compose_indoors.solve_large_enabled=False',
          'compose_indoors.solve_medium_enabled=False','compose_indoors.floating_objs_enabled=False',
          'populate_doors.casing_chance=1.0',
          "RoomConstants.global_params.wall_height=('uniform', 2.8, 2.8)"])
    env={**os.environ,'CUDA_VISIBLE_DEVICES':'','MPLBACKEND':'Agg',
         'PYTHONPATH':str(ROOT/'modules/infinigen'),'PYTHONUNBUFFERED':'1',
         'OMP_NUM_THREADS':'8','OPENBLAS_NUM_THREADS':'8'}
    state={'scene_id':args.scene,'seed':args.seed,'argv':cmd,'gpu':'disabled',
           'phase':'generating','started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
           'plan_sha256':checked['floor_plan_sha256'],'work':str(work)}
    statefile=work/'generation_state.json'
    statefile.write_text(json.dumps(state,indent=2))
    with (work/'generation.log').open('w') as log:
        proc=subprocess.run(cmd,cwd='/root/module/infinigen',env=env,stdout=log,stderr=subprocess.STDOUT)
    state.update(returncode=proc.returncode,phase='generated' if proc.returncode==0 else 'failed',
                 finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 scene_exists=(full/'scene.blend').is_file())
    statefile.write_text(json.dumps(state,indent=2));print(json.dumps(state,indent=2))
    raise SystemExit(proc.returncode)
