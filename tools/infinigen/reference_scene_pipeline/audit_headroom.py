"""Bounded tread-centre physical headroom rays; visibility flags cannot mask hits."""
import argparse,hashlib,json,sys
from pathlib import Path
import bpy
from mathutils import Vector
p=argparse.ArgumentParser();p.add_argument('--blend',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]);bpy.ops.wm.open_mainfile(filepath=str(a.blend.resolve()));bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();rays=[]
for o in bpy.data.objects:
 if o.get('audit_kind')!='stair_tread' or 'tread' not in o.get('program_key',''):continue
 points=[o.matrix_world@Vector(c) for c in o.bound_box];center=sum(points,Vector())/8;top=max(v.z for v in points)
 hit,point,normal,index,obj,matrix=bpy.context.scene.ray_cast(deps,Vector((center.x,center.y,top+.01)),Vector((0,0,1)),distance=6);clearance=point.z-top if hit else None
 rays.append({'tread':o.name,'clearance_m':clearance,'hit':obj.name if hit else None,'pass':clearance is None or clearance>=2})
assert rays,'No actual tread geometry found'
doc={'source':str(a.blend.resolve()),'source_sha256':hashlib.sha256(a.blend.read_bytes()).hexdigest(),'rays':rays,'all_pass':all(row['pass'] for row in rays),'scope':'Vertical rays at tread centres only. Not complete swept-body, building-code or upper-floor circulation certification.'};a.out.write_text(json.dumps(doc,indent=2));print(json.dumps({'treads':len(rays),'all_pass':doc['all_pass']}))
