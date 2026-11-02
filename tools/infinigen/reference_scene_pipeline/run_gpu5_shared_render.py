"""One GPU5 render under current SONNET shared grant; codex yields on pressure.

Never edits another holder's row or signals any other process. No OOM GPU retry.
Combined memory limit uses conservative decimal22GB, not card capacity.
"""
import argparse
import fcntl
import json
import os
import socket
import subprocess
import time
from pathlib import Path

R=Path(__file__).resolve().parents[3]
T=Path(__file__).parent
LOCK=Path('/bean/ir_dataset_work/gpu_pool.lock.json')
LIMIT_BYTES=22_000_000_000
UUID='GPU-750c6b29-484e-f119-728b-bd4ebc38869a'


def allocation():
    data=json.loads(LOCK.read_text())
    assert data['all_holders'].get('CODEX_INFINIGEN')==[5], 'Own GPU5 claim missing'
    assert 5 in data['all_holders'].get('IR_DATASET_INFINIGEN_ORCHESTER',[])
    grant=next(r for r in reversed(data['claims_log']) if r.get('gpu')==5 and r.get('kind')=='shared-permission')
    assert 'codex_infinigen yields first' in grant['note']
    return grant


def memory():
    out=subprocess.run(['nvidia-smi','-i','5','--query-gpu=uuid,memory.used,memory.total,utilization.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True,check=True).stdout.strip()
    uid,used,total,util=[p.strip() for p in out.split(',')]
    assert uid==UUID,'Physical GPU5 UUID changed; revalidate assignment'
    return {'uuid':uid,'used_mib':int(used),'total_mib':int(total),'utilization_percent':int(util),'observed_unix':time.time()}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--blend',type=Path,required=True)
    p.add_argument('--views',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--estimated-memory-mib',type=int,required=True)
    p.add_argument('--samples',type=int,default=32)
    p.add_argument('--threads',type=int,default=8)
    p.add_argument('--preserve-source-lighting',action='store_true')
    a=p.parse_args();assert a.estimated_memory_mib>=512
    d=a.out.resolve().parent;assert not d.exists();d.mkdir(parents=True)
    job={'pid':os.getpid(),'host':socket.gethostname(),'phase':'validating_shared_allocation','source':str(a.blend.resolve()),'views':str(a.views.resolve()),'out':str(a.out.resolve()),'device':'OPTIX','physical_gpu':5,'cuda_visible_devices':'5','combined_limit_bytes':LIMIT_BYTES,'estimated_memory_mib':a.estimated_memory_mib,'started_unix':time.time(),'yield_priority':'CODEX_INFINIGEN_FIRST'}
    def save(): (d/'job.json').write_text(json.dumps(job,indent=2)+'\n')
    save()
    with open('/tmp/robomituba_codex_infinigen_gpu5_render.lock','a+') as serial:
        try:fcntl.flock(serial,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            job.update(phase='refused_other_own_gpu_render_live');save();return 2
        job['allocation']=allocation();initial=memory();job['initial_gpu_memory']=initial
        if (initial['used_mib']+a.estimated_memory_mib)*1048576>LIMIT_BYTES:
            job.update(phase='yielded_before_launch_insufficient_shared_headroom');save();return 3
        command=['python3',str(R/'tools/infinigen/run_bundled_blender.py'),'-t',str(a.threads),'--background','--python-exit-code','1','--python',str(T/'render_with_load_receipt.py'),'--','--blend',job['source'],'--launch-report',str(d/'load.json'),'--views',job['views'],'--out',job['out'],'--device','OPTIX','--threads',str(a.threads),'--samples',str(a.samples)]
        if a.preserve_source_lighting:command.append('--preserve-source-lighting')
        job['command']=command
        samples=[];yield_reason=None
        with (d/'render.log').open('w') as log:
            child=subprocess.Popen(command,cwd=R,env={**os.environ,'CUDA_VISIBLE_DEVICES':'5'},stdout=log,stderr=subprocess.STDOUT)
            job.update(phase='live',child_pid=child.pid);save()
            while child.poll() is None:
                try:
                    allocation();sample=memory();samples.append(sample)
                    if sample['used_mib']*1048576>LIMIT_BYTES:
                        yield_reason='combined22GB_limit_exceeded'
                except Exception as error:
                    yield_reason='allocation_or_memory_observation_lost:'+repr(error)
                if yield_reason:
                    # Exact own Popen handle; no nvidia-smi PID or peer process is signalled.
                    child.terminate()
                    try:child.wait(timeout=20)
                    except subprocess.TimeoutExpired:child.kill();child.wait()
                    break
                time.sleep(3)
            code=child.wait()
        text=(d/'render.log').read_text(errors='replace')
        oom=any(term in text.lower() for term in ['cuda error: out of memory','cuda_error_out_of_memory','out of gpu memory','optix error: memory allocation'])
        if oom:yield_reason='cuda_or_optix_oom_codex_yields_no_retry'
        job.update(exit_code=code,phase='yielded_gpu5' if yield_reason else ('rendered_visual_review_pending' if code==0 else 'failed'),yield_reason=yield_reason,finished_unix=time.time(),peak_combined_used_mib=max([initial['used_mib']]+[x['used_mib'] for x in samples]))
        (d/'gpu_memory_samples.json').write_text(json.dumps(samples,indent=2)+'\n');save()
        return code if code else (4 if yield_reason else 0)


if __name__=='__main__':raise SystemExit(main())
