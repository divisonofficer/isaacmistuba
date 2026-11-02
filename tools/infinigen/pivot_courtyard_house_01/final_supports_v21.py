"""Add explicit shelf feet, motor hangers and countertop plinth; preserve rendered composition."""
import bpy,json,sys
from pathlib import Path
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools/infinigen'))
from room_planner import proc_assets as pa
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full';oak=bpy.data.materials['pivot_r16_residential_oak'];steel=bpy.data.materials['layout_v2_steel'];dark=bpy.data.materials['layout_v2_dark_frame']
def box(c,s):return ('box',c,s,(0,0,0))
parts=[box((27.05,y,(.145542+.2775)/2),(.60,.045,.2775-.145542)) for y in [9.70,11.50,13.30]]
o=pa._prims('PivotGarageV21_grounded_shelf_feet',[(oak,parts)]);o['ir_room']='garage_0/0'
parts=[box((x,11.50,(2.475+2.65646)/2),(.025,.025,2.65646-2.475)) for x in [28.50,28.80]]+[box((x,y,(2.6195+2.65646)/2),(.04,.04,2.65646-2.6195)) for x in [28.10,31.30] for y in [9.46,13.54]]
o=pa._prims('PivotGarageV21_ceiling_supports',[(steel,parts)]);o['ir_room']='garage_0/0'
o=pa._prims('PivotPantryV21_recessed_plinth',[(dark,[box((19.30,9.43,(.14555+.16055)/2),(1.90,.44,.015))])]);o['ir_room']='utility_0/1'
bpy.context.view_layer.update();bpy.context.scene['pivot_revision']='quality_rework_v21';bpy.context.scene['pivot_candidate_status']='integrated work in progress; full reference and regression acceptance pending';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_integrated_v21.blend'));(B/'support_stage_v21.json').write_text(json.dumps({'status':'geometry_saved_physical_audit_pending','supports':[{'object':'PivotGarageV21_grounded_shelf_feet','floor_z':.145542,'top_z':.2775,'reason':'Existing shelf unit lower panel and sides started 132mm above floor; explicit feet close this unsupported gap'},{'object':'PivotGarageV21_ceiling_supports','from_motor_top_z':2.475,'ceiling_attachment_top_z':2.65646,'reason':'Connect motor and track brackets to actual ceiling'},{'object':'PivotPantryV21_recessed_plinth','bottom_z':.14555,'top_z':.16055,'reason':'Ground second pantry base cabinet while retaining recessed toe line'}],'remaining':['Support contact bounds audit','Final all-camera render review and packing']},indent=2)+'\n');print('PIVOT_SUPPORTS_V21_SAVED',flush=True)
