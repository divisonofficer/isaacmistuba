"""Use installed bpy runtime; caller holds Blender lock and clears CUDA."""
import sys,runpy
from pathlib import Path
import bpy
source=Path(sys.argv[1]).resolve()
assert source.name=='scene_mat2_activity.blend'
bpy.ops.wm.open_mainfile(filepath=str(source))
sys.argv=[sys.argv[0],'--',*sys.argv[2:]]
runpy.run_path(str(Path(__file__).with_name('ratio1_pkg_c_verify.py')),run_name='__main__')
