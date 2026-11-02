"""Shorten the new breakfast bar to leave a genuinely comfortable dining connection."""
import bpy,json
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full'
o=bpy.data.objects['PivotCourtyardV10_family_breakfast_counter'];inv=o.matrix_world.inverted()
for v in o.data.vertices:
 p=o.matrix_world@v.co;p.x=15.625-(15.625-p.x)*(3.75/4.25);v.co=inv@p
for i in range(3):bpy.data.objects['CounterStoolFactory(%d).spawn_asset(%d)'%(3010+i,3010+i)].location.x+=.25
bpy.context.view_layer.update();bpy.context.scene['pivot_revision']='quality_rework_v24';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_integrated_v24.blend'));(B/'family_passage_stage_v24.json').write_text(json.dumps({'status':'geometry_saved_repeat_route_audit_pending','reason':'After laundry leaf correction, the 0.60m family route still touched the authored opening return wall. The original 4.25m breakfast bar left an unnecessarily narrow connection.','counter_width_before_m':4.25,'counter_width_after_m':3.75,'counter_left_edge_x':11.875,'approx_walk_gap_to_opening_return_m':1.13,'stools':'Three retained and re-centered','route_center_x':11.31,'audit_body_width_m':.60},indent=2)+'\n');print('PIVOT_FAMILY_PASSAGE_V24_SAVED',flush=True)
