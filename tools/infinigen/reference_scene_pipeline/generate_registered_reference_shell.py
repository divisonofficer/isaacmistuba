"""CPU-only native Infinigen architecture for a registered new reference.
No API planner, furniture stand-ins or dataset promotion. Project-local engine.
"""
import argparse,datetime,hashlib,json,os,subprocess,sys,traceback
from pathlib import Path
R=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(R/'scripts'));sys.path.insert(0,str(Path(__file__).parent))
from infinigen_gen import parse_seed,build_command
from preflight import audit

def main():
 p=argparse.ArgumentParser();p.add_argument('scene');a=p.parse_args();ref=R/'data/venue_refs/floor_plans_v3'/a.scene
 slots=json.loads((ref.parent/'scene_slots.json').read_text())['slots'];row=next(r for r in slots if r['scene_id']==a.scene)
 assert row['slot']>=4 and not row.get('user_approved') and not row.get('dataset_promoted'),'Only unapproved new slots'
 contract=json.loads((ref/'scene_contract.json').read_text());checked=audit(ref);assert checked['status']=='pass',checked['failures'];(ref/'preflight_layout.json').write_text(json.dumps(checked,indent=2)+'\n')
 engine=R/'modules/infinigen';assert (engine/'infinigen_examples/generate_indoors.py').exists()
 os.environ['INFINIGEN_DIR']=str(engine);os.environ['INFINIGEN_PYTHON']='/root/miniconda3/envs/infinigen/bin/python'
 seed=contract['seed'];work=R/'out/infinigen_v2'/f'kr_{a.scene}_{seed}';full=work/'full';assert not (full/'scene.blend').exists();assert not (work/'generation_state.json').exists(),'Keep earlier attempt receipts'
 full.mkdir(parents=True,exist_ok=True);preset=parse_seed(seed);preset.floor_plan_key='reference_authored';height=contract['wall_height_m'];thickness=contract['wall_thickness_m'];assert 2.2<=height<=6 and .1<=thickness<=.8
 overrides=['compose_indoors.solve_large_enabled=False','compose_indoors.solve_medium_enabled=False','compose_indoors.solve_small_enabled=False','compose_indoors.floating_objs_enabled=False','populate_doors.casing_chance=1.0','RoomConstants.n_stories=1',f"RoomConstants.global_params.wall_height=('uniform',{height},{height})",f"RoomConstants.global_params.wall_thickness=('uniform',{thickness},{thickness})",'RoomConstants.global_params.segment_margin=1.8']
 command=build_command(preset,out=full,stage='full',fast=False,floor_plan_json=ref/'floor_plan.json',base_config='vanilla',small_objects='activity',extra_overrides=overrides)
 env={**os.environ,'CUDA_VISIBLE_DEVICES':'','MPLBACKEND':'Agg','PYTHONPATH':str(engine),'PYTHONUNBUFFERED':'1','OMP_NUM_THREADS':'8','OPENBLAS_NUM_THREADS':'8','ROBOMITUBA_INFINIGEN_OFFICE_STYLE':'','ROBOMITUBA_DOOR_STYLE':'','ROBOMITUBA_INFINIGEN_ROOM_TYPE':'','ROBOMITUBA_INFINIGEN_PROGRAM':''}
 state={'pid':os.getpid(),'scene_id':a.scene,'seed':seed,'phase':'starting','device':'CPU','engine_root':str(engine),'cwd':str(engine),'argv':command,'plan_sha256':checked['floor_plan_sha256'],'output':str(full),'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Indoor architecture first. No detailed rural stone/timber/roof/exterior or furniture completion claimed.','photorealism_accepted':False,'dataset_promoted':False}
 path=work/'generation_state.json'
 def save():path.write_text(json.dumps(state,indent=2)+'\n')
 save()
 try:
  with (work/'generation.log').open('w') as log:
   child=subprocess.Popen(command,cwd=engine,env=env,stdout=log,stderr=subprocess.STDOUT);state.update(phase='generating_native_architecture',child_pid=child.pid);save();code=child.wait()
  state.update(phase='architecture_generated_validation_pending' if code==0 else 'failed',exit_code=code,scene_exists=(full/'scene.blend').exists(),finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat());save()
 except BaseException as error:state.update(phase='failed',error=repr(error),traceback=traceback.format_exc());save();raise
 print(json.dumps(state,indent=2),flush=True);return code

if __name__=='__main__':raise SystemExit(main())
