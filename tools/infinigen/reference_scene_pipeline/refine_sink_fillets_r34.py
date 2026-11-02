"""True planar sink floor/walls with constant-radius fillets; readable manufactured drain."""
import bpy,bmesh,math,json,hashlib
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';source=base/'scene_candidate_r33.blend';out=base/'scene_candidate_r34.blend';assert not out.exists();sha=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source));floor=bpy.data.objects['kitchen_0/0.floor'];top=max((floor.matrix_world@Vector(c)).z for c in floor.bound_box)+.9175;steel=bpy.data.materials['SinkR31_satin_stainless']
for o in list(bpy.data.objects):
 if o.get('program_key') in ['sink_formed_bowl','sink_strainer']:bpy.data.objects.remove(o,do_unlink=True)
def mark(o,key):o['reference_scene_owner']='commercial_office_floor_02';o['program_key']=key;o['audit_kind']='fixture' if key=='sink_formed_bowl' else 'detail';return o
def rr(hx,hy,r,z):
 points=[];segments=24
 if abs(hx-r)<1e-9 and abs(hy-r)<1e-9:return [(14.275+hx*math.cos(math.tau*k/100),4.65+hy*math.sin(math.tau*k/100),z) for k in range(100)]
 for j,(cx,cy) in enumerate([(hx-r,hy-r),(-hx+r,hy-r),(-hx+r,-hy+r),(hx-r,-hy+r)]):
  for k in range(segments+1):
   a=j*math.pi/2+k*math.pi/2/segments;points.append((14.275+cx+r*math.cos(a),4.65+cy+r*math.sin(a),z))
 return points
# Inner wall top roll, straight drafted walls, true quarter-circle bottom bend, then a flat floor.
inner=[(.345,.300,.002,top+.003),(.230,.265,.060,top+.003)]
for k in range(1,13):
 a=k*math.pi/2/12;delta=.015*math.sin(a);inner.append((.230-delta,.265-delta,.060-delta,top+.003-.015*(1-math.cos(a))))
for depth in [.04,.08,.125]:
 t=(depth-.012)/(.125-.012);inner.append((.215-.015*t,.250-.015*t,.045,top-depth))
for k in range(1,13):
 a=k*math.pi/2/12;delta=.025*(1-math.cos(a));inner.append((.200-delta,.235-delta,.045-delta,top-.125-.025*math.sin(a)))
inner.append((.026,.026,.026,top-.150));floor_index=len(inner)-2
# Inner drain wall and underside. Supports from r32 remain in place.
outer=[(hx+.0015,hy+.0015,r+.0015,z-.0015) for hx,hy,r,z in reversed(inner[1:])];profile=inner+outer+[(.345,.300,.002,top)];N=100;verts=[p for ring in profile for p in rr(*ring)];faces=[]
for j in range(len(profile)):
 for k in range(N):faces.append((j*N+k,j*N+(k+1)%N,((j+1)%len(profile))*N+(k+1)%N,((j+1)%len(profile))*N+k))
mesh=bpy.data.meshes.new('SinkR34_manufactured_shell');mesh.from_pydata(verts,[],faces);mesh.materials.append(steel);bm=bmesh.new();bm.from_mesh(mesh);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));closed=all(e.is_manifold for e in bm.edges);bm.to_mesh(mesh);bm.free();assert closed
for j in range(len(profile)):
 planar=abs(profile[j][3]-profile[(j+1)%len(profile)][3])<1e-7
 for f in list(mesh.polygons)[j*N:(j+1)*N]:f.use_smooth=not planar
obj=bpy.data.objects.new('SinkR34_planar_floor_fillet_shell',mesh);bpy.context.scene.collection.objects.link(obj);mark(obj,'sink_formed_bowl');obj['closed_shell']=True
floor_faces=list(mesh.polygons)[floor_index*N:(floor_index+1)*N];assert all(abs(abs(f.normal.z)-1)<1e-5 and not f.use_smooth for f in floor_faces)
# Real ring, radial strainer slots and removable centre cap, not a featureless hole.
def part(key,verts,faces):
 me=bpy.data.meshes.new(key);me.from_pydata(verts,[],faces);me.materials.append(steel);o=bpy.data.objects.new('SinkR34_'+key,me);bpy.context.scene.collection.objects.link(o);return mark(o,key)
z=top-.149
v=[];f=[]
for radius,zz in [(.031,z),(.022,z),(.022,z-.004),(.031,z-.004)]:v.extend([(14.275+radius*math.cos(math.tau*k/96),4.65+radius*math.sin(math.tau*k/96),zz) for k in range(96)])
for j in range(4):
 for k in range(96):f.append((j*96+k,j*96+(k+1)%96,((j+1)%4)*96+(k+1)%96,((j+1)%4)*96+k))
part('sink_strainer_ring',v,f)
pattern=[(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)];cube_faces=[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
for k in range(12):
 a=math.tau*k/12;v=[]
 for sx,sy,sz in pattern:
  x=.0175+sx*.0055;y=sy*.0014;v.append((14.275+x*math.cos(a)-y*math.sin(a),4.65+x*math.sin(a)+y*math.cos(a),z-.0015+sz*.001))
 part('sink_strainer_bridge_'+str(k),v,cube_faces)
v=[(14.275+.0125*math.cos(math.tau*k/64),4.65+.0125*math.sin(math.tau*k/64),zz) for zz in [z-.004,z-.001] for k in range(64)];f=[(k,(k+1)%64,64+(k+1)%64,64+k) for k in range(64)]+[tuple(reversed(range(64))),tuple(range(64,128))];part('sink_strainer_centre_cap',v,f)
# New wood candidate is too bright/pink in AgX; calibrate diffuse reflectance, leaving lighting/exposure untouched.
m=bpy.data.materials['BreakoutR33_vertical_oak_veneer'];bs=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED');old=bs.inputs['Base Color'].links[0].from_socket;mix=m.node_tree.nodes.new('ShaderNodeMixRGB');mix.blend_type='MULTIPLY';mix.inputs[0].default_value=1;mix.inputs[2].default_value=(.68,.68,.68,1);m.node_tree.links.new(old,mix.inputs[1]);m.node_tree.links.new(mix.outputs[0],bs.inputs['Base Color'])
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(source.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r34.json').write_text(json.dumps({'source':str(source),'candidate':str(out),'source_sha256':sha,'trigger':'Independent r32 review: melted sink,unclear floor/wall/drain; r33 wood too bright/pink','changes':['constant15mm upper roll and25mm wall/floor fillet','drafted straight walls and truly planar floor with flat normals','annular strainer,12radial bridges and centre cap; actual holes remain','oak diffuse reflectance multiplied .68;no exposure/light change'],'closed_manifold':closed,'flat_floor_faces':len(floor_faces),'flat_floor_normal_check':True,'bowl_depth_m':.15,'photorealism_accepted':False,'next':'same sink camera plus a clearly labelled higher drain inspection camera; independent review'},indent=2));print('SAVED',out)
