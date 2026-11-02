"""Actual evaluated step/stringer support rays, then bounded structural correction."""
import bpy,bmesh,json,math,os,traceback
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/double_height_duplex_09';B=R/'out/infinigen_v2/kr_double_height_duplex_09_48712509/full';src=B/'scene_candidate_r003.blend';out=B/'scene_candidate_r004.blend';assert not out.exists();job={'pid':os.getpid(),'phase':'stair_actual_mesh_contact_audit','source':str(src),'device':'CPU'};jp=D/'build_r004_job.json';jp.write_text(json.dumps(job,indent=2));bpy.ops.wm.open_mainfile(filepath=str(src))
def audit():
 bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();trees=[]
 for o in bpy.context.scene.objects:
  if o.name.startswith('Inclined_steel_stair_stringer'):
   e=o.evaluated_get(dg);m=e.to_mesh();trees.append(BVHTree.FromPolygons([o.matrix_world@v.co for v in m.vertices],[list(p.vertices)for p in m.polygons]));e.to_mesh_clear()
 rows=[]
 for o in sorted([o for o in bpy.context.scene.objects if o.name.startswith('Stair_tread_')],key=lambda o:o.name):
  e=o.evaluated_get(dg);m=e.to_mesh();vs=[o.matrix_world@v.co for v in m.vertices];lo=Vector([min(v[k]for v in vs)for k in range(3)]);hi=Vector([max(v[k]for v in vs)for k in range(3)]);e.to_mesh_clear();samples=[]
  for x in[9.82,10.78]:
   origin=Vector((x,(lo.y+hi.y)/2,lo.z+.5));hits=[t.ray_cast(origin,Vector((0,0,-1)),1)[0]for t in trees];hits=[h for h in hits if h is not None];gap=lo.z-max(h.z for h in hits)if hits else None;samples.append({'x_m':x,'actual_tread_bottom_z_m':lo.z,'vertical_support_gap_m':gap,'contact':gap is not None and -.035<=gap<=.002})
  rows.append({'tread':o.name,'actual_riser_top_z_m':hi.z,'support_probes':samples})
 return rows
try:
 before=audit();dark=bpy.data.materials['Blackened bronze frames']
 for o in list(bpy.context.scene.objects):
  if o.name.startswith('Inclined_steel_stair_stringer'):bpy.data.objects.remove(o,do_unlink=True)
 for i,x in enumerate([9.82,10.78]):
  a=Vector((x,4.75,-.0716));b=Vector((x,10.85,3.385));bpy.ops.mesh.primitive_cube_add(size=1,location=(a+b)/2);o=bpy.context.object;o.name='Inclined_steel_stair_stringer_corrected_'+str(i);o.dimensions=(.13,.13,(b-a).length);bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.rotation_euler=(b-a).to_track_quat('Z','Y').to_euler();o.data.materials.append(dark);bpy.ops.object.transform_apply(location=True,rotation=True,scale=True);bm=bmesh.new();bm.from_mesh(o.data);cut=bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=.000001,plane_co=Vector((0,0,3.395)),plane_no=Vector((0,0,1)),clear_outer=True);edges=[e for e in cut['geom_cut'] if isinstance(e,bmesh.types.BMEdge)];bmesh.ops.holes_fill(bm,edges=edges,sides=0);bm.to_mesh(o.data);bm.free()
  m=o.modifiers.new('Steel edge arris','BEVEL');m.width=.004;m.segments=3
 after=audit();assert all(p['contact']for r in after for p in r['support_probes']),after
 bpy.ops.wm.save_as_mainfile(filepath=str(out));(D/'views_r004.json').write_text((D/'views_r003.json').read_text());(D/'stair_actual_contact_r004.json').write_text(json.dumps({'source':str(src),'candidate':str(out),'actual_before':before,'actual_after':after,'all40_corrected_probes_contact':True,'scope':'Actual evaluated20tread undersides against2real stringer mesh ray hits;positive gap<=2mm, penetration<=35mm. Upper stringer cap below3.4m landingfloor. Not stairload/engineering certification, doorroute or image approval.','acceptance':False},indent=2));job.update(phase='saved_render_pending',candidate=str(out),exit_code=0)
except BaseException as e:job.update(phase='failed',error=repr(e),traceback=traceback.format_exc(),exit_code=1);raise
finally:jp.write_text(json.dumps(job,indent=2));print(job,flush=True)
