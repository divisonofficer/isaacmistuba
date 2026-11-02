"""Generate a real Infinigen tree prototype on CPU for the next review round."""
import bpy,json
from pathlib import Path
from infinigen.assets.objects.trees.generate import TreeFactory
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
factory=TreeFactory(48712901,season='summer',fruit_chance=0,realize=False)
o=factory.spawn_asset(0)
o.name='PivotNativeLandscapeTree';o['pivot_native_landscape_tree']=True
bpy.context.view_layer.update()
p=Path('/jarvis/project/robomituba/out/infinigen_v2/kr_pivotHouse_48712501/full/landscape_tree.blend')
bpy.ops.wm.save_as_mainfile(filepath=str(p));print('NATIVE_TREE_COMPLETE',o.name,list(o.dimensions),flush=True)
