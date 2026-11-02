"""Control: fresh fitted shirt should stay at rest without gravity, pins or collisions."""
from pathlib import Path
import json
source_script=Path(__file__).with_name('garment_mass_corrected_pilot01.py')
code=source_script.read_text().split('for frame in range(1,61):')[0]
code=code.replace('garment_mass_corrected_pilot01','garment_zero_force_control')
exec(compile(code,str(source_script),'exec'))
proto=prototypes[0];cm=proto.modifiers['Gravity_on_actual_hanger'];cm.settings.vertex_group_mass='';cm.collision_settings.use_collision=False;cm.collision_settings.use_self_collision=False;scene.gravity=(0,0,0)
rows=[]
for frame in range(1,13):
 scene.frame_set(frame);ev=proto.evaluated_get(bpy.context.evaluated_depsgraph_get());me=ev.to_mesh();extent=[max(v.co[k] for v in me.vertices)-min(v.co[k] for v in me.vertices) for k in range(3)];edges=sum((me.vertices[e.vertices[0]].co-me.vertices[e.vertices[1]].co).length for e in me.edges)/len(me.edges);rows.append({'frame':frame,'extent_m':extent,'mean_edge_length_m':edges});ev.to_mesh_clear()
 result={'phase':'complete' if frame==12 else 'evaluating','rows':rows,'gravity':[0,0,0],'pins':False,'external_collision':False,'self_collision':False,'actual_total_mass_kg':float(cm.settings.mass)*len(proto.data.vertices),'scope':'rest-state diagnostic only; no scene save or integration'}
 (ref/'garment_zero_force_control.json').write_text(json.dumps(result,indent=2));print('CONTROL_FRAME',frame,extent,edges,flush=True)
