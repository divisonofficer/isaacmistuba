"""Durable exit receipt for one owned Blender build, never a retry controller."""
import argparse,json,os,subprocess,time,traceback
from pathlib import Path
R=Path(__file__).resolve().parents[3]
p=argparse.ArgumentParser();p.add_argument('--script',type=Path,required=True);p.add_argument('--job-dir',type=Path,required=True);a=p.parse_args();D=a.job_dir.resolve();assert not D.exists();D.mkdir(parents=True)
state={'pid':os.getpid(),'phase':'starting','script':str(a.script.resolve()),'started_unix':time.time(),'device':'CPU'}
def save():(D/'job.json').write_text(json.dumps(state,indent=2)+'\n')
try:
 command=['python3',str(R/'tools/infinigen/run_bundled_blender.py'),'-t','8','--background','--python-exit-code','1','--python',state['script']];state['command']=command
 with (D/'build.log').open('w') as log:
  child=subprocess.Popen(command,cwd=R,env={**os.environ,'CUDA_VISIBLE_DEVICES':''},stdout=log,stderr=subprocess.STDOUT);state.update(phase='live',child_pid=child.pid);save();code=child.wait()
 state.update(phase='built_validation_pending' if code==0 else 'failed',exit_code=code,finished_unix=time.time());save()
except BaseException as error:state.update(phase='failed',error=repr(error),traceback=traceback.format_exc());save();raise
raise SystemExit(code)
