"""12-frame corrected-mass controls isolate hanger and self-collision effects; no room save."""
from pathlib import Path
import json,argparse
parser=argparse.ArgumentParser();parser.add_argument("--mode",choices=["gravity_pins","gravity_pins_self","gravity_pins_external","gravity_pins_external_narrow"],required=True);args=parser.parse_args()
source_script=Path(__file__).with_name('garment_mass_corrected_pilot01.py')
code=source_script.read_text().split('for frame in range(1,61):')[0]
code=code.replace('garment_mass_corrected_pilot01','garment_force_'+args.mode)
if args.mode=='gravity_pins_external_narrow':
 code=code.replace('(-.18,0,-.075)','(-.13,0,-.075)').replace('(.18,0,-.075)','(.13,0,-.075)').replace('side*.18','side*.13').replace('ax/.18','ax/.13').replace('.12<side*q.x<.19','.085<side*q.x<.135').replace('abs(q.x)-.16','abs(q.x)-.11')
exec(compile(code,str(source_script),'exec'))
proto=prototypes[0];cm=proto.modifiers['Gravity_on_actual_hanger'];cm.collision_settings.use_collision=args.mode in ['gravity_pins_external','gravity_pins_external_narrow'];cm.collision_settings.use_self_collision=args.mode=='gravity_pins_self'
rows=[]
for frame in range(1,13):
 scene.frame_set(frame);ev=proto.evaluated_get(bpy.context.evaluated_depsgraph_get());me=ev.to_mesh();extent=[max(v.co[k] for v in me.vertices)-min(v.co[k] for v in me.vertices) for k in range(3)];edges=sum((me.vertices[e.vertices[0]].co-me.vertices[e.vertices[1]].co).length for e in me.edges)/len(me.edges);rows.append({'frame':frame,'extent_m':extent,'mean_edge_length_m':edges});ev.to_mesh_clear()
 result={'phase':'complete' if frame==12 else 'evaluating','rows':rows,'mode':args.mode,'gravity':list(scene.gravity),'pins':True,'external_collision':cm.collision_settings.use_collision,'self_collision':cm.collision_settings.use_self_collision,'actual_total_mass_kg':float(cm.settings.mass)*len(proto.data.vertices),'scope':'rest-state diagnostic only; no scene save or integration'}
 (ref/('garment_force_'+args.mode+'.json')).write_text(json.dumps(result,indent=2));print('CONTROL_FRAME',frame,extent,edges,flush=True)
