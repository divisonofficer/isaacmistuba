"""One-prototype early trajectory; controlled self-collision on/off. Never saves a scene."""
import sys,os,json
from pathlib import Path
script=Path(__file__).with_name('settle_garments_on_hangers_r41.py');code=script.read_text().split('for frame in range(1,61):')[0]
code=code.replace('assert not out.exists();','').replace('range(6)','range(1)').replace("state=ref/'hanger_settlement_r41_job.json'","state=ref/('early_solver_'+os.environ['CLOTH_SELF_COLLISION']+'_job.json')")
if os.environ['CLOTH_SELF_COLLISION']=='pin_clearance':code=code.replace('*(.0022+.0015)','*(.0022+.0027)')
if os.environ['CLOTH_SELF_COLLISION']=='native_fit':
 code=code.replace('scale=min(1,.47/(bounds[0][1]-bounds[0][0]),.59/(bounds[2][1]-bounds[2][0]))','scale=min(1,.59/(bounds[2][1]-bounds[2][0]))').replace('wire_z+.004','wire_z+.008').replace('*(.0022+.0015)','*(.0022+.0027)')
exec(compile(code,str(script),'exec'))
active=os.environ['CLOTH_SELF_COLLISION'] in ['on','thin_wire','pin_clearance','supported_constraints','native_fit'];proto=prototypes[0];proto.modifiers['Gravity_on_actual_hanger'].collision_settings.use_self_collision=active
if os.environ['CLOTH_SELF_COLLISION'] in ['no_external','supported_constraints']:proto.modifiers['Gravity_on_actual_hanger'].collision_settings.use_collision=False
print('WIRE_DEFAULTS',json.dumps([{'inner':c.collision.thickness_inner,'outer':c.collision.thickness_outer,'use_culling':c.collision.use_culling} for c in colliders]),flush=True)
if os.environ['CLOTH_SELF_COLLISION']=='thin_wire':
 for collider in colliders:collider.collision.thickness_inner=.0005
rows=[]
for frame in range(1,61 if os.environ['CLOTH_SELF_COLLISION'] in ['supported_constraints','native_fit'] else 13):
 scene.frame_set(frame);dg=bpy.context.evaluated_depsgraph_get();ev=proto.evaluated_get(dg);me=ev.to_mesh();pts=[v.co-origins[0] for v in me.vertices];row={'frame':frame,'bounds':[[min(p[k] for p in pts) for k in range(3)],[max(p[k] for p in pts) for k in range(3)]],'mean_edge_length_m':sum((me.vertices[e.vertices[0]].co-me.vertices[e.vertices[1]].co).length for e in me.edges)/len(me.edges)};rows.append(row);ev.to_mesh_clear();print('EARLY_SOLVER',active,row,flush=True)
 (ref/('early_solver_'+os.environ['CLOTH_SELF_COLLISION']+'.json')).write_text(json.dumps({'source':str(source),'self_collision':active,'control':os.environ['CLOTH_SELF_COLLISION'],'pin_surface_gap_m':.0027 if os.environ['CLOTH_SELF_COLLISION']=='pin_clearance' else .0015,'pattern':0,'rows':rows,'scope':'Single-prototype trajectory diagnostic only;not visual/final physics acceptance;scene never saved'},indent=2))

if os.environ['CLOTH_SELF_COLLISION'] in ['supported_constraints','native_fit']:
 import numpy as np
 ev=proto.evaluated_get(bpy.context.evaluated_depsgraph_get());me=ev.to_mesh();np.savez_compressed(ref/(os.environ['CLOTH_SELF_COLLISION']+'_pattern0.npz'),vertices=np.asarray([list(v.co-origins[0]) for v in me.vertices]),faces=np.asarray([list(f.vertices) for f in me.polygons],dtype=object));ev.to_mesh_clear()
