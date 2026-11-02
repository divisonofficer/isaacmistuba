"""Observe native scene loading, then execute unchanged render.py under its own __file__."""
import bpy,argparse,sys,json,os,time,runpy,traceback
from pathlib import Path
args=sys.argv[sys.argv.index('--')+1:];p=argparse.ArgumentParser();p.add_argument('--blend',type=Path,required=True);p.add_argument('--launch-report',type=Path,required=True);a,render_args=p.parse_known_args(args);a.launch_report.parent.mkdir(parents=True,exist_ok=True);state={'pid':os.getpid(),'source':str(a.blend.resolve()),'phase':'loading_source','started_unix':time.time()}
def save():a.launch_report.write_text(json.dumps(state,indent=2));print('RENDER_LOAD_STATE',state['phase'],flush=True)
try:
 save();bpy.ops.wm.open_mainfile(filepath=str(a.blend.resolve()));state.update(phase='source_loaded',loaded_unix=time.time());save();renderer=Path(__file__).with_name('render.py');sys.argv=[str(renderer),'--',*render_args];state['phase']='rendering';save();runpy.run_path(str(renderer),run_name='__main__');state.update(phase='rendered',finished_unix=time.time());save()
except BaseException as error:
 state.update(phase='failed',error=repr(error),traceback=traceback.format_exc());save();raise
