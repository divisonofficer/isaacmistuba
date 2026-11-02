"""Rebuild the defective door-head wall finish as an attached plaster solid."""
import bpy,json,sys
from pathlib import Path
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools/infinigen'))
from room_planner import proc_assets as pa
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full'
m=bpy.data.materials.new('guest_v36_repaired_lintel_plaster');m.use_nodes=True;p=m.node_tree.nodes['Principled BSDF'];p.inputs['Base Color'].default_value=(.86181,.83646,.78803,1);p.inputs['Roughness'].default_value=.8
o=pa._prims('PivotGuestV36_repaired_lintel_finish',[(m,[('box',(20.151,1.35,(2.51+2.6544578)/2),(.020,.50,2.6544578-2.51),(0,0,0))])]);o['ir_room']='bedroom_0/4';o['ir_role']='attached_plaster_lintel_finish'
bpy.context.view_layer.update();bpy.context.scene['pivot_revision']='quality_rework_v36_lintel_finish_candidate';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_integrated_v36.blend'))
(B/'guest_lintel_finish_v36.json').write_text(json.dumps({'status':'saved_small_same_view_gate_pending','source_scene':'scene_rework_integrated_v35.blend','reason':'V35 normal correction did not resolve the raster black triangle; no acceptance was inferred from corrected polygon normals.','repair':'20mm solid plaster finish embedded over the damaged door-head wall patch; original ceiling and room layout retained','bounds':[[20.141,20.161],[1.10,1.60],[2.51,2.6544578]],'remaining':['Actual same-camera render must show repaired wall surface','Door and casing clearance/contact check','Final complete render consistency']},ensure_ascii=False,indent=2)+'\n');print('PIVOT_GUEST_LINTEL_V36_SAVED',flush=True)
