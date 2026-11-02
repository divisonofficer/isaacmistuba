"""Finish actual board-to-tool retaining clips before freezing the integrated candidate."""
import bpy,json,sys
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools/infinigen'))
from room_planner import proc_assets as pa
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full'
steel=bpy.data.materials['garage_v31_brushed_tool_steel'];rows=[]
def bb(o):
    p=[o.matrix_world@Vector(v) for v in o.bound_box];return [[min(v[i] for v in p),max(v[i] for v in p)] for i in range(3)]
for i,x in enumerate([28.48,28.76,29.04,29.32],1):
    parts=[('box',(x,9.243,1.68),(.09,.008,.016),(0,0,0))]
    parts += [('box',(xx,9.218,1.68),(.012,.054,.016),(0,0,0)) for xx in [x-.039,x+.039]]
    o=pa._prims('PivotGarageV39_tool_retaining_clip_'+str(i),[(steel,parts)]);o['ir_room']='garage_0/0';o['ir_role']='board_anchored_tool_retaining_clip'
    bpy.context.view_layer.update();tool=bpy.data.objects['PivotGarageV31_wall_tool_'+str(i)];a,c=bb(o),bb(tool)
    contact=[min(a[k][1],c[k][1])-max(a[k][0],c[k][0]) for k in range(3)]
    assert all(v>0 for v in contact),(i,contact)
    rows.append({'clip':o.name,'tool':tool.name,'intended_retaining_contact_aabb_overlap_m':contact,'board_front_y':9.2025,'clip_back_y':a[1][0]})
bpy.context.scene['pivot_revision']='quality_rework_v39_frozen_candidate';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_integrated_v39.blend'))
(B/'tool_mounts_v39.json').write_text(json.dumps({'status':'mount_contact_verified_full_visual_regression_pending','source_scene':'scene_rework_integrated_v38.blend','mounted_tools':rows,'remaining':['Full 37-view direct review of frozen candidate','Final packing and high-resolution actual Blender overview','Report/dataset/local inspection consistency']},indent=2)+'\n');print('PIVOT_TOOL_MOUNTS_V39_SAVED',flush=True)
