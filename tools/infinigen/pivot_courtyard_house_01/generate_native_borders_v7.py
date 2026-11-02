"""Generate genuine Infinigen shrubs and grasses on CPU, preserving engine provenance."""
import bpy,json
from pathlib import Path
from infinigen.assets.objects.trees.generate import BushFactory
from infinigen.assets.objects.grassland.grass_tuft import GrassTuftFactory
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
rows=[]
for i in range(3):
 factory=BushFactory(48712660+i,realize=True);o=factory.spawn_asset(i);o.name='PivotNativeBushV6_'+str(i);o['pivot_border_prototype']=True;bpy.context.view_layer.update();rows.append({'name':o.name,'factory':'BushFactory','seed':48712660+i,'dimensions':list(o.dimensions)});print('NATIVE_BORDER_CREATED',o.name,flush=True)
f=GrassTuftFactory(48712670);o=f.spawn_asset(4);f.finalize_assets([o]);o.name='PivotNativeGrassV6';o['pivot_border_prototype']=True;rows.append({'name':o.name,'factory':'GrassTuftFactory','seed':48712670,'dimensions':list(o.dimensions)})
R=Path(__file__).resolve().parents[3];p=R/'out/infinigen_v2/kr_pivotHouse_48712501/full/native_borders_v7.blend';bpy.ops.wm.save_as_mainfile(filepath=str(p));(p.with_suffix('.json')).write_text(json.dumps(rows,indent=2));print('NATIVE_BORDERS_V7_SAVED',flush=True)
