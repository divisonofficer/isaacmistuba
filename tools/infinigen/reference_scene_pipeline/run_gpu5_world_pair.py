"""Sequential shared-GPU A/B with exact renderer/camera/lighting receipts.
No acceptance or retry, and never concurrent own GPU children.
"""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
R=Path(__file__).resolve().parents[3];T=Path(__file__).parent
p=argparse.ArgumentParser();p.add_argument('--baseline-blend',type=Path,required=True);p.add_argument('--candidate-blend',type=Path,required=True);p.add_argument('--views',type=Path,required=True);p.add_argument('--out-dir',type=Path,required=True);p.add_argument('--estimated-memory-mib',type=int,required=True);a=p.parse_args();D=a.out_dir.resolve();assert not D.exists();D.mkdir(parents=True)
state={'pid':os.getpid(),'phase':'starting','baseline_source':str(a.baseline_blend.resolve()),'candidate_source':str(a.candidate_blend.resolve()),'views':str(a.views.resolve()),'started_unix':time.time(),'device':'OPTIX','physical_gpu':5}
def save():(D/'job.json').write_text(json.dumps(state,indent=2)+'\n')
save();receipts=[]
for label,source in [('baseline',a.baseline_blend),('candidate',a.candidate_blend)]:
 command=[sys.executable,str(T/'run_gpu5_shared_render.py'),'--blend',str(source.resolve()),'--views',str(a.views.resolve()),'--out',str(D/(label+'_job')/'candidate'),'--estimated-memory-mib',str(a.estimated_memory_mib),'--samples','48']
 with (D/(label+'_manager.log')).open('w') as log:
  child=subprocess.Popen(command,cwd=R,stdout=log,stderr=subprocess.STDOUT)
  state.update(phase='rendering_'+label,manager_child_pid=child.pid);save();code=child.wait()
 state[label+'_exit_code']=code
 if code:
  state.update(phase=label+'_failed_or_yielded',finished_unix=time.time());save();raise SystemExit(code)
 receipts.append(json.loads((D/(label+'_job')/'candidate/render_receipt.json').read_text()))
base,candidate=receipts
for field in ['device','cuda_visible_devices','renderer_sha256','lighting_policy','lighting_overrides','denoising']:
 assert base[field]==candidate[field],field
assert base['source_unchanged'] and candidate['source_unchanged']
assert [f['name'] for f in base['frames']]==[f['name'] for f in candidate['frames']]
pairs=[]
for x,y in zip(base['frames'],candidate['frames']):
 for field in ['camera','width','height','samples']:assert x[field]==y[field],field
 pairs.append({'name':x['name'],'baseline':x,'candidate':y})
contract={'baseline_source':base['source'],'baseline_sha256':base['source_sha256'],'candidate_source':candidate['source'],'candidate_sha256':candidate['source_sha256'],'renderer_sha256':base['renderer_sha256'],'same_device_camera_resolution_samples_renderer_policy':True,'authored_world_intentionally_changed':True,'lighting_scope':'Identical renderer override policy and recorded override values only; authored world differs intentionally. This is not equal scene illumination.','pairs':pairs,'visual_acceptance':False}
(D/'matched_AB_contract.json').write_text(json.dumps(contract,indent=2)+'\n');state.update(phase='rendered_matched_pair_visual_review_pending',finished_unix=time.time());save()
