"""Export actual failed native-neck control andnearest segment evidence;not a new parameter trial."""
from pathlib import Path
import json,math
ROOT=Path(__file__).resolve().parents[3];diagnostic_dir=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/native_neck_hanger06_diagnostic';assert not diagnostic_dir.exists() or not any(diagnostic_dir.iterdir());diagnostic_dir.mkdir(exist_ok=True)
def capture_failure():
 import bpy
 from mathutils import Vector
 debug=[]
 for j in sorted(range(len(clear)),key=lambda i:clear[i])[:5]:
  a,b=segments[j];n=max(1,math.ceil((b-a).length/.0005));hits=[]
  for k in range(n+1):
   q=a.lerp(b,k/n);hit,normal,face,d=tree.find_nearest(q);hits.append((d,q,hit,normal,face))
  d,q,hit,normal,face=min(hits,key=lambda x:x[0]);debug.append({'segment':j,'start':list(a),'end':list(b),'minimum_sample_distance_m':d,'conservative_lower_bound_m':clear[j],'wire_sample':list(q),'closest_cloth_surface':list(hit),'cloth_face':face,'cloth_normal':list(normal)})
 proof.update(phase='failed_initial_control_diagnostic',closest_segments=debug,manual_neck_face_deletion=False,physics_solve_started=False,room_integrated=False,photorealism_accepted=False,scope='Actual native-neck control06;neutral geometry diagnostic only. No successful physical settlement orscene integration.')
 for o in list(bpy.data.objects):
  if o!=shirt:bpy.data.objects.remove(o,do_unlink=True)
 shirt.data.materials.clear();m=bpy.data.materials.new('Neutral diagnostic cloth');m.use_nodes=True;m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=(.32,.38,.43,1);m.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value=.8;shirt.data.materials.append(m)
 for f in shirt.data.polygons:f.material_index=0;f.use_smooth=True
 c=bpy.data.curves.new('Measured wire diagnostic','CURVE');c.dimensions='3D';c.bevel_depth=radius;c.bevel_resolution=3;s=c.splines.new('POLY');s.points.add(len(wire)-2)
 for dst,co in zip(s.points,wire[:-1]):dst.co=(*co,1)
 s.use_cyclic_u=True;o=bpy.data.objects.new(c.name,c);bpy.context.collection.objects.link(o);mat=bpy.data.materials.new('Red wire diagnostic');mat.use_nodes=True;mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=(.55,.035,.015,1);c.materials.append(mat)
 scene=bpy.context.scene;scene.world=scene.world or bpy.data.worlds.new('DiagnosticWorld');scene.world.use_nodes=True;scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.2
 for name,loc,power,size in [('key',(-.5,-.6,.4),45,.5),('fill',(.4,.1,.3),15,.3)]:
  d=bpy.data.lights.new(name,'AREA');d.energy=power;d.size=size;o=bpy.data.objects.new(name,d);bpy.context.collection.objects.link(o);o.location=loc;o.rotation_euler=(Vector((0,0,-.15))-o.location).to_track_quat('-Z','Y').to_euler()
 views=[{'name':'native_neck_clearance_failure','location':[0,-.38,.14],'target':[0,0,-.025],'hfov':60,'render_width':640,'samples':16}];(diagnostic_dir/'views.json').write_text(json.dumps(views,indent=2));(diagnostic_dir/'scope.json').write_text(json.dumps(proof,indent=2));bpy.ops.wm.save_as_mainfile(filepath=str(diagnostic_dir/'studio.blend'));print('Captured failed control. Worst segments:',json.dumps(debug[:2]),flush=True);return False
path=Path(__file__).with_name('build_native_roof_hanger_pilot06.py');code=path.read_text().replace('garment_roof_hanger_pilot06','garment_roof_hanger_neck_diagnostic06')
# The outer control executes source04;inject the capture into its preflight guard.
needle="assert code.count(needle)==1;code=code.replace(needle,replacement);exec(compile(code,str(path),'exec'))"
replacement="assert code.count(needle)==1;code=code.replace(needle,replacement);code=code.replace(\"assert proof['pass'],'Initial wire/body preflight failed'\",\"assert proof['pass'] or capture_failure(),'Initial wire/body preflight failed'\");exec(compile(code,str(path),'exec'))"
assert code.count(needle)==1;code=code.replace(needle,replacement)
try:exec(compile(code,str(path),'exec'))
except AssertionError:
 assert (diagnostic_dir/'studio.blend').exists(),'Unexpected failure before diagnostic capture';print('Diagnostic export succeeded;physical initial gate remains FAILED',flush=True)
