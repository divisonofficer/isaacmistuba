"""Supervise a long CPU render independently of an interactive command session."""
import argparse,datetime,hashlib,json,os,socket,subprocess,sys
from pathlib import Path
from PIL import Image

p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--state',type=Path,required=True);p.add_argument('--log',type=Path,required=True);a=p.parse_args()
assert not os.environ.get('CUDA_VISIBLE_DEVICES'),'CPU-only render job'
def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
if a.state.exists():
    previous=json.loads(a.state.read_text())
    if previous.get('phase') in ('starting','running') and Path('/proc',str(previous.get('supervisor_pid'))).exists():
        raise RuntimeError('Existing live supervisor: no duplicate render launched')
source=a.source.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
state={'phase':'starting','supervisor_pid':os.getpid(),'hostname':socket.gethostname(),'source':str(source),'source_sha256':sha(source),'output':str(out),'log':str(a.log.resolve()),'device':'CPU','cuda_visible_devices':os.environ.get('CUDA_VISIBLE_DEVICES'),'dimensions':[3840,2560],'samples':64,'started_at':now()}
def save():
    state['updated_at']=now();tmp=a.state.with_suffix('.tmp');tmp.write_text(json.dumps(state,indent=2)+'\n');tmp.replace(a.state)
save()
renderer=Path(__file__).with_name('render_plan_overview.py').resolve()
code='import bpy,runpy,sys; bpy.ops.wm.open_mainfile(filepath='+repr(str(source))+'); sys.argv='+repr(['render_plan_overview.py','--','--out',str(out),'--width','3840','--height','2560','--samples','64'])+'; runpy.run_path('+repr(str(renderer))+',run_name="__main__")'
cmd=['/root/miniconda3/envs/infinigen/bin/python','-u','-c',code]
try:
    with open(a.log,'wb') as log:
        worker=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'CUDA_VISIBLE_DEVICES':''})
        state.update(phase='running',worker_pid=worker.pid,worker_python=cmd[0]);save()
        result=worker.wait()
    state.update(returncode=result,finished_at=now())
    if result!=0:raise RuntimeError('Renderer exited '+str(result))
    png=out/'overview.png';provenance=json.loads((out/'overview_provenance.json').read_text())
    with Image.open(png) as im:im.load();size=list(im.size)
    assert size==[3840,2560] and provenance['dimensions']==size
    assert sha(source)==provenance['source_sha256']==state['source_sha256']
    assert sha(png)==provenance['render_sha256']
    state.update(phase='complete',render=str(png),render_sha256=provenance['render_sha256'],png_fully_decoded=True,source_unchanged=True);save()
except BaseException as error:
    state.update(phase='failed',error=str(error),finished_at=now());save();raise
