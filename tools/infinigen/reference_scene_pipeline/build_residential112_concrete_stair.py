"""Construct actual closed-riser waist-slab stair geometry, not furnishing proxies."""
import bpy,bmesh,json,hashlib
from pathlib import Path
from mathutils import Vector
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';b=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';src=b/'scene_candidate_r108_draft.blend';dst=b/'scene_candidate_r112_draft.blend';assert not dst.exists();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();before=sha(src);bpy.ops.wm.open_mainfile(filepath=str(src));floor=bpy.data.objects['bedroom_0/0.floor'];fz=max((floor.matrix_world@Vector(c)).z for c in floor.bound_box);removed=[]
for o in list(bpy.context.scene.objects):
 if o.get('audit_kind') in ['stair_tread','stair_support']:removed.append(o.name);bpy.data.objects.remove(o,do_unlink=True)
assert len(removed)>=19
mat=bpy.data.materials['res03_stone'].copy();mat.name='Residential112_concrete_stair_structure';rail=bpy.data.materials.new('Residential112_painted_steel_guard');rail.use_nodes=True;bs=rail.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(.075,.08,.085,1);bs.inputs['Roughness'].default_value=.38;bs.inputs['Metallic'].default_value=0 # painted steel coating is dielectric
for o in bpy.context.scene.objects:
 if o.type=='MESH' and o.get('audit_kind')=='stair_guard':
  for i in range(len(o.data.materials)):o.data.materials[i]=rail
made=[]
def prism(name,x0,x1,profile):
 n=len(profile);verts=[(x,y,z) for x in [x0,x1] for y,z in profile];faces=[tuple(reversed(range(n))),tuple(range(n,2*n))]+[(i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n)];me=bpy.data.meshes.new(name);me.from_pydata(verts,[],faces);bm=bmesh.new();bm.from_mesh(me);bmesh.ops.recalc_face_normals(bm,faces=bm.faces);assert all(e.is_manifold for e in bm.edges);bm.to_mesh(me);bm.free();o=bpy.data.objects.new(name,me);bpy.context.scene.collection.objects.link(o);o.data.materials.append(mat);o['program_key']=name;o['audit_kind']='stair_structure';o['reference_scene_owner']='dual_unit_residential_floor_03';be=o.modifiers.new('Real concrete edge arris 2mm','BEVEL');be.width=.002;be.segments=3;bpy.context.view_layer.objects.active=o;o.select_set(True);bpy.ops.object.modifier_apply(modifier=be.name);o.select_set(False);made.append(o);return o
pitch=.29;rise=.15;N=9;start=11.65;end=start+pitch*N
for name,x0,x1,y0,sgn,z0 in [('lower',9.35,10.45,start,1,fz),('upper',11.05,12.15,end,-1,fz+1.35)]:
 profile=[(y0,z0)]
 for i in range(N):profile.extend([(y0+sgn*i*pitch,z0+(i+1)*rise),(y0+sgn*(i+1)*pitch,z0+(i+1)*rise)])
 profile.extend([(y0+sgn*N*pitch,z0+N*rise-.18),(y0,z0-.18)]);prism('Residential112_concrete_'+name,x0,x1,profile)
prism('Residential112_concrete_half_landing',9.35,12.15,[(end,fz+1.35),(15.35,fz+1.35),(15.35,fz+1.17),(end,fz+1.17)])
bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();rays=[]
for name,x,y0,sgn,z0 in [('lower',9.9,start,1,fz),('upper',11.6,end,-1,fz+1.35)]:
 for i in range(N):
  y=y0+sgn*(i+.5)*pitch;z=z0+(i+1)*rise;hit,p,n,j,obj,m=bpy.context.scene.ray_cast(deps,Vector((x,y,z+.01)),Vector((0,0,1)),distance=6);gap=p.z-z if hit else None;rays.append({'flight':name,'step':i,'clearance_m':gap,'hit':obj.name if hit else None,'pass':gap is None or gap>=2.0})
assert all(x['pass'] for x in rays),rays
bpy.ops.wm.save_as_mainfile(filepath=str(dst));assert sha(src)==before;(d/'stair112_build.json').write_text(json.dumps({'source':str(src),'source_sha256':before,'candidate':str(dst),'candidate_sha256':sha(dst),'removed':removed,'new_objects':[o.name for o in made],'flight_width_m':1.1,'rise_m':rise,'going_m':pitch,'steps_per_flight':N,'floor_to_floor_m':2.7,'waist_vertical_depth_m':.18,'landing_top_z_m':fz+1.35,'headroom_samples':rays,'scope':'Actual closed-riser extruded concrete construction with2mm edge arris. Existing guard geometry retained and finish changed to painted steel. Centerline vertical headroom only; full foot clearance/guard gaps/nav and visual review outstanding. Source108 branch; unreviewed bedroom111 trial not included.','accepted':False},indent=2));print('RESIDENTIAL112_CONCRETE_STAIR_SAVED')
