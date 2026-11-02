"""Durable CPU render manager with source-load stages and actual exit receipts."""
import argparse,subprocess,json,os,time,traceback
from pathlib import Path
R=Path(__file__).resolve().parents[3];T=Path(__file__).parent;p=argparse.ArgumentParser();p.add_argument('--blend',type=Path,required=True);p.add_argument('--views',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--samples',type=int,default=48);p.add_argument('--threads',type=int,default=8);p.add_argument('--preserve-source-lighting',action='store_true');a=p.parse_args();D=a.out.resolve().parent;assert not D.exists();D.mkdir(parents=True);job={'pid':os.getpid(),'phase':'starting','source':str(a.blend.resolve()),'views':str(a.views.resolve()),'out':str(a.out.resolve()),'started_unix':time.time(),'device':'CPU'};jp=D/'job.json'
def save():jp.write_text(json.dumps(job,indent=2))
try:
 command=['python3',str(R/'tools/infinigen/run_bundled_blender.py'),'-t',str(a.threads),'--background','--python-exit-code','1','--python',str(T/'render_with_load_receipt.py'),'--','--blend',job['source'],'--launch-report',str(D/'load.json'),'--views',job['views'],'--out',job['out'],'--device','CPU','--threads',str(a.threads),'--samples',str(a.samples)]
 if a.preserve_source_lighting:command.append('--preserve-source-lighting')
 job['command']=command;save()
 with (D/'render.log').open('w') as f:
  child=subprocess.Popen(command,cwd=R,env={**os.environ,'CUDA_VISIBLE_DEVICES':''},stdout=f,stderr=subprocess.STDOUT);job.update(phase='live',child_pid=child.pid);save();code=child.wait()
 job.update(phase='rendered_visual_review_pending' if code==0 else 'failed',exit_code=code,finished_unix=time.time());save()
except BaseException as error:job.update(phase='failed',error=repr(error),traceback=traceback.format_exc());save();raise
raise SystemExit(code)
