"""Reduce miniature tree repetition and let broad-leaf understory form the front layer."""
import bpy, json
from pathlib import Path
from mathutils import Vector,Matrix
R=Path(__file__).resolve().parents[3];B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full'
hidden=[]
for i in range(15):
    root=bpy.data.objects['PivotLeafyV9_low_shrub_'+str(i)]
    for o in [root,*root.children_recursive]:o.hide_render=True
    hidden.append(root.name)
adjusted=[]
meta=json.loads((B/'native_underplanting_v29.json').read_text())
for row in meta['plants']:
    if row['role']!='border':continue
    o=bpy.data.objects[row['root']];anchor=Vector(row['soil_root'])
    o.matrix_world=Matrix.Translation(anchor)@Matrix.Diagonal((1.30,1.12,1.22,1))@Matrix.Translation(-anchor)@o.matrix_world
    adjusted.append({'root':o.name,'root_preserved':list(anchor),'scale_xy_z':[1.30,1.12,1.22]})
bpy.context.view_layer.update();bpy.context.scene['pivot_revision']='quality_rework_v32_understory_balance_candidate';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_integrated_v32.blend'))
(B/'understory_balance_v32.json').write_text(json.dumps({'status':'saved_same_courtyard_view_pending','source':'scene_rework_integrated_v31.blend','reason':'Repeated miniature mature trunks dominated the previous low layer even after adding broad leaves.','hidden_repeated_low_tree_roots':hidden,'broadleaf_adjustments':adjusted,'preserved':['Mature courtyard tree','Rear and side leafy shrub layers','Flower and grass layer','Soil, glazing, paths and room layout'],'remaining':['Direct same-camera density and botanical hierarchy review','Current geometry ground/root and route checks','Final whole-house consistency']},ensure_ascii=False,indent=2)+'\n');print('PIVOT_UNDERSTORY_BALANCE_V32_SAVED',len(hidden),len(adjusted),flush=True)
