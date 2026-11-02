"""Run one owned reconstruction stage. No LLM planner/reviewer API calls.

GPU render must be launched separately after SONNET_GPU_MANAGER allocates it.
All stages here run with CUDA_VISIBLE_DEVICES empty.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
REF = ROOT / 'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01'
SEED = 48712501
WORK = ROOT / f'out/infinigen_v2/kr_pivotHouse_{SEED}'
F = WORK / 'full'
IGPY = '/root/miniconda3/envs/infinigen/bin/python'
TOOLS = ROOT / 'tools/infinigen'

def main():
 ap = argparse.ArgumentParser()
 ap.add_argument('stage', choices=['generate','materials','architecture','extract','furnish','finish','lighting','probe'])
 a = ap.parse_args()
 F.mkdir(parents=True, exist_ok=True)
 env = {**os.environ, 'CUDA_VISIBLE_DEVICES':'', 'PYTHONUNBUFFERED':'1',
        'PYTHONPATH':str(ROOT/'modules/infinigen'),
        'OMP_NUM_THREADS':'8','OPENBLAS_NUM_THREADS':'8',
        'INFINIGEN_DIR':'/root/module/infinigen','INFINIGEN_PYTHON':IGPY,
        'ROOM_BASEBOARD':'1','ROOM_FLAT_WALLS':'1','ROOM_RELAX_ZONES':'1',
        'ROOM_OPEN_BLINDS':'1','ROOM_OPEN_DOORS':'1','PROBE_HFOV':'70',
        'ROOM_WALL_TILE_ROOMS':'bathroom','ROOM_WALL_TILE':'0.62,0.60,0.57',
        'ROOM_FLOOR_TILE_ROOMS':'kitchen,utility,bathroom,living-room,dining-room,hallway',
        'ROOM_FLOOR_TILE':'0.62,0.60,0.57','ROOM_TILE_SIZE':'0.6',
        'ROBOMITUBA_INFINIGEN_PLACEMENT_PROFILE':'collision_aware_clutter_v1'}
 cwd = '/tmp'
 if a.stage == 'generate':
  sys.path.insert(0,str(ROOT/'scripts'))
  from infinigen_gen import parse_seed, build_command
  preset = parse_seed(SEED); preset.floor_plan_key = 'pivot_custom'
  cmd = build_command(preset,out=F,stage='full',fast=False,
    floor_plan_json=REF/'floor_plan.json',base_config='vanilla',small_objects='activity',
    extra_overrides=['compose_indoors.solve_large_enabled=False',
      'compose_indoors.solve_medium_enabled=False','compose_indoors.floating_objs_enabled=False',
      'populate_doors.casing_chance=1.0',
      "RoomConstants.global_params.wall_height=('uniform', 2.8, 2.8)"])
  cwd = '/root/module/infinigen'
  shutil.copy2(REF/'floor_plan.json',F/'floor_plan.json')
 elif a.stage == 'materials':
  cmd = ['python3',str(TOOLS/'run_bundled_blender.py'),'-t','8','--background',str(F/'scene.blend'),
    '--python-exit-code','1','--python',str(TOOLS/'rematerial_rooms_infinigen2.py'),
    '--','--out',str(F/'scene_mat2.blend'),'--seed',str(SEED),'--style',str(REF/'kit.json')]
 elif a.stage == 'architecture':
  cmd=[IGPY,str(TOOLS/'architecture_pass.py'),str(F/'scene_mat2.blend'),'--out',str(F/'scene_arch.blend'),
       '--seed',str(SEED),'--palette',str(REF/'kit.json'),'--archetype','apartment']
 elif a.stage == 'extract':
  cmd=[IGPY,str(Path(__file__).with_name('extract_rooms.py')),str(F/'scene_arch.blend'),'--out',str(F/'rooms.json')]
 elif a.stage == 'furnish':
  plans=json.loads((F/'plans.json').read_text())
  assert all(e['plan'].get('fixed') is True for e in plans['rooms'].values()), 'Every plan must disable API revision with fixed=true'
  cmd=[IGPY,str(Path(__file__).with_name('furnish.py')),str(F/'scene_arch.blend'),
    '--out',str(F/'scene_mat2_activity.blend'),'--solve-state',str(F/'solve_state.json'),
    '--seed',str(SEED),'--abo','--plans',str(F/'plans.json')]
 elif a.stage == 'finish':
  cmd=[IGPY,str(Path(__file__).with_name('finish_scene.py')),str(F/'scene_mat2_activity.blend'),
       '--out',str(F/'scene_fitted.blend')]
 elif a.stage == 'lighting':
  cmd=[IGPY,str(TOOLS/'kit_lighting.py'),str(F/'scene_fitted.blend'),
    '--out',str(F/'scene_lit.blend'),'--plans',str(F/'plans.json'),'--seed',str(SEED)]
 else:
  cmd=[IGPY,'/tmp/claude-0/objreal/probe_views.py',str(F/'scene_lit.blend'),str(F/'views.json'),'0']
 record={'stage':a.stage,'argv':cmd,'cwd':cwd,'host':socket.gethostname(),'PYTHONPATH':env['PYTHONPATH'],
   'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'gpu':'disabled',
   'planning_owner':'this Codex session; fixed manual plans, direct image inspection'}
 state=WORK/(a.stage+'_state.json');state.write_text(json.dumps(record,indent=2))
 print(json.dumps(record,indent=2),flush=True)
 with (WORK/(a.stage+'.log')).open('w') as log:
  p=subprocess.run(cmd,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT)
 record.update(returncode=p.returncode,finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
 state.write_text(json.dumps(record,indent=2));print(json.dumps(record,indent=2),flush=True)
 return p.returncode

if __name__=='__main__':
 raise SystemExit(main())
