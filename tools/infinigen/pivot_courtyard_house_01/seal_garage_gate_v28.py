"""Close light leaks in the closed gate with an attached rear skin and seals."""
import bpy, json, sys
from pathlib import Path
from mathutils import Vector

R=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(R/'tools/infinigen'))
from room_planner import proc_assets as pa
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01'
F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full'
gate=bpy.data.objects['PivotSectionalGarageDoorFactory(1303).spawn_asset(1303)']
rubber=bpy.data.materials.new('garage_v28_gate_rubber');rubber.use_nodes=True
bs=rubber.node_tree.nodes['Principled BSDF'];bs.inputs['Base Color'].default_value=(.018,.02,.019,1);bs.inputs['Roughness'].default_value=.85
parts=[('box',(32.858,11.5,1.39),(.018,4.40,2.50),(0,0,0))]
skin=pa._prims('PivotGarageV28_closed_gate_rear_skin',[(rubber,parts)])
world=skin.matrix_world.copy();skin.parent=gate;skin.matrix_world=world
skin['ir_room']='garage_0/0';skin['ir_role']='closed_gate_attached_rear_skin'
skin['not_architectural_wall']=True
# Frame-attached perimeter gasket hides the residual bright perimeter slits.
parts=[('box',(32.735,y,1.39),(.045,.06,2.50),(0,0,0)) for y in (9.315,13.685)]
parts.extend([('box',(32.735,11.5,z),(.045,4.43,.065),(0,0,0)) for z in (.135,2.61)])
seal=pa._prims('PivotGarageV28_perimeter_weather_seals',[(rubber,parts)])
seal['ir_room']='garage_0/0';seal['ir_role']='garage_gate_frame_weather_seal'
bpy.context.view_layer.update()
# The gate skin is separate from the house envelope. Hide the closed assembly
# to retain an actual traversable vehicle opening in the architectural wall.
gate.hide_set(True);skin.hide_set(True);bpy.context.view_layer.update()
hit,p,n,f,o,m=bpy.context.scene.ray_cast(bpy.context.evaluated_depsgraph_get(),Vector((33.6,11.5,1)),Vector((-1,0,0)),distance=8)
proof={'object':o.name if o else None,'point':list(p),'closed_gate_assembly_temporarily_hidden':True}
assert hit and p.x<28,proof
gate.hide_set(False);skin.hide_set(False);bpy.context.view_layer.update()
bpy.context.scene['pivot_revision']='quality_rework_v28_gate_seal_candidate'
bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_integrated_v28.blend'))
(B/'garage_seals_v28.json').write_text(json.dumps({'status':'saved_original_gate_view_render_pending','source':'scene_rework_integrated_v27.blend','changes':['Gate-attached opaque rear skin behind existing sectional panels','Frame perimeter rubber gasket'],'vehicle_opening_proof':proof,'remaining':['Direct garage gate view: no bright panel or perimeter leaks','Re-run physical audit and whole-scene consistency before final delivery']},ensure_ascii=False,indent=2)+'\n')
print('PIVOT_GATE_SEALS_V28_SAVED',proof,flush=True)
