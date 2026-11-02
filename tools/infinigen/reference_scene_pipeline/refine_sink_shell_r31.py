"""Replace an assembled slab sink with a continuous pressed stainless shell and covered aperture."""
import bpy,bmesh,json,hashlib,math
from pathlib import Path
from mathutils import Vector
from material_detail import material,noise,bump,range_value
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';source=base/'scene_candidate_r30.blend';out=base/'scene_candidate_r31.blend';assert not out.exists();sha=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source));floor=bpy.data.objects['kitchen_0/0.floor'];fz=max((floor.matrix_world@Vector(c)).z for c in floor.bound_box);top=fz+.9175
removed=[]
for o in list(bpy.data.objects):
 if o.get('program_key','').startswith('sink_'):removed.append(o.name);bpy.data.objects.remove(o,do_unlink=True)
m,n,l,bs,tc,geo=material('SinkR31_satin_stainless',(.58,.59,.60),.27,1);broad=noise(n,l,geo.outputs['Position'],4);l.new(range_value(n,l,broad,.24,.30),bs.inputs['Roughness']);micro=noise(n,l,geo.outputs['Position'],550,(1,8,1));l.new(bump(n,l,micro,.000002,.1),bs.inputs['Normal']);bs.inputs['Anisotropic'].default_value=.35;m['reference_pbr_kind']='bare_metal'
# Cross section from underside drain to outer rectangular aperture edge, rounded rim, inner bowl and drain.
profile=[(.025,.025,top-.166,2),(.16,.19,top-.166,4),(.195,.23,top-.152,4),(.215,.25,top-.006,5),(.345,.300,top,0),(.345,.300,top+.003,0),(.225,.260,top+.003,5),(.219,.254,top-.004,5),(.208,.243,top-.045,5),(.195,.230,top-.125,4),(.170,.200,top-.158,3),(.025,.025,top-.164,2)];N=128;vertices=[]
for rx,ry,z,power in profile:
 for k in range(N):
  t=math.tau*k/N;c=math.cos(t);s=math.sin(t)
  if power==0:r=1/max(abs(c),abs(s));x=rx*c*r;y=ry*s*r
  else:x=rx*math.copysign(abs(c)**(2/power),c);y=ry*math.copysign(abs(s)**(2/power),s)
  vertices.append((14.275+x,4.65+y,z))
faces=[]
for j in range(len(profile)):
 nj=(j+1)%len(profile)
 for k in range(N):faces.append((j*N+k,j*N+(k+1)%N,nj*N+(k+1)%N,nj*N+k))
mesh=bpy.data.meshes.new('SinkR31_continuous_pressed_shell');mesh.from_pydata(vertices,[],faces);mesh.materials.append(m);bm=bmesh.new();bm.from_mesh(mesh);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));manifold=all(e.is_manifold for e in bm.edges);bm.to_mesh(mesh);bm.free();assert manifold
for f in mesh.polygons:f.use_smooth=True
# Outer mounting skirt is flat, not a soft-normal cap averaged into the bowl.
for j in [4,5]:
 for f in list(mesh.polygons)[j*N:(j+1)*N]:f.use_smooth=False
o=bpy.data.objects.new('SinkR31_pressed_stainless_bowl',mesh);bpy.context.scene.collection.objects.link(o);o['reference_scene_owner']='commercial_office_floor_02';o['program_key']='sink_formed_bowl';o['audit_kind']='fixture';o['closed_shell']=True
# Actual annular strainer at the open drain, with a small recessed removable centre plug.
verts=[];fs=[]
for r,z in [(.030,top-.162),(.020,top-.162),(.020,top-.169),(.030,top-.169)]:
 verts.extend([(14.275+r*math.cos(math.tau*k/64),4.65+r*math.sin(math.tau*k/64),z) for k in range(64)])
for j in range(4):
 for k in range(64):fs.append((j*64+k,j*64+(k+1)%64,((j+1)%4)*64+(k+1)%64,((j+1)%4)*64+k))
me=bpy.data.meshes.new('Sink_strainer_ring');me.from_pydata(verts,[],fs);me.materials.append(m);obj=bpy.data.objects.new('SinkR31_strainer',me);bpy.context.scene.collection.objects.link(obj);obj['reference_scene_owner']='commercial_office_floor_02';obj['program_key']='sink_strainer';obj['audit_kind']='detail'
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(source.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r31.json').write_text(json.dumps({'source':str(source),'candidate':str(out),'source_sha256':sha,'trigger':'r29 closeup shows black uncovered gaps at slab sink/aperture ends','removed_slab_parts':removed,'new_shell_quads':len(faces),'closed_manifold':manifold,'outer_aperture_m':[.69,.60],'bowl_depth_m':.164,'actual_mounting_lip_m':.003,'micro_bump_distance_m':.000002,'requires':'same camera inspect perimeter,drain and curved wall highlights','photorealism_accepted':False},indent=2));print('SAVED',out,flush=True)
