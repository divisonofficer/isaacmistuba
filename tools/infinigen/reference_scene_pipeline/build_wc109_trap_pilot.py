"""Actual open swept S-trap diagnostic. No plug/disc, no water mask, no room adoption."""
import bpy,json,math,hashlib,bmesh
from pathlib import Path
from mathutils import Vector
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';p=d/'wc109_trap_pilot';assert not p.exists();p.mkdir();src=d/'native_fullsize_wc100/product.blend';source_sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));original=bpy.data.objects['NativeFullTankWC100'];inlet=json.loads((d/'wc109_trap_inlet.json').read_text());cx,cy=inlet['center_xy_m'];N=64
# Neutral checker floor is a diagnostic visibility target, not a scene/product stand-in.
mat=bpy.data.materials.new('Diagnostic_floor_checker');mat.use_nodes=True;n=mat.node_tree.nodes;bs=n.get('Principled BSDF');tex=n.new('ShaderNodeTexChecker');tex.inputs['Color1'].default_value=(.07,.12,.20,1);tex.inputs['Color2'].default_value=(.65,.34,.12,1);tex.inputs['Scale'].default_value=12;coord=n.new('ShaderNodeTexCoord');mat.node_tree.links.new(coord.outputs['Generated'],tex.inputs['Vector']);mat.node_tree.links.new(tex.outputs['Color'],bs.inputs['Base Color']);bs.inputs['Roughness'].default_value=.7
me=bpy.data.meshes.new('Diagnostic_floor');me.from_pydata([(-1,-1,-.004),(1,-1,-.004),(1,1,-.004),(-1,1,-.004)],[],[(0,1,2,3)]);me.materials.append(mat);o=bpy.data.objects.new(me.name,me);bpy.context.scene.collection.objects.link(o)
for i,(pos,power) in enumerate([((.7,-1,1.8),90),((-.8,.5,1.2),45)]):
 ld=bpy.data.lights.new('Diagnostic_area'+str(i),'AREA');ld.energy=power;ld.size=.8;o=bpy.data.objects.new(ld.name,ld);bpy.context.scene.collection.objects.link(o);o.location=pos;o.rotation_euler=(Vector((0,0,.4))-o.location).to_track_quat('-Z','Y').to_euler()
w=bpy.data.worlds.new('WC109_neutral_world');w.use_nodes=True;w.node_tree.nodes.get('Background').inputs['Strength'].default_value=.12;bpy.context.scene.world=w
bpy.ops.wm.save_as_mainfile(filepath=str(p/'baseline.blend'))
# Ring tuples: inner and outer wall sections. Adapter matches measured native inlet.
rings=[]
for j in range(13):
 t=j/12;z=.156+(.125-.156)*t;rr=[]
 for radius,key in [(.025,'inner_ring_xy'),(.031,'outer_ring_xy')]:
  rr.append([((1-t)*xy[0]+t*(cx+radius*math.cos(2*math.pi*i/N)),(1-t)*xy[1]+t*(cy+radius*math.sin(2*math.pi*i/N)),z) for i,xy in enumerate(inlet[key])])
 rings.append(rr)
centers=[]
for j in range(1,9):centers.append((cx,.125-(.025*j/8)))
for j in range(1,49):
 a=math.pi*j/48;centers.append((cx-.05+.05*math.cos(a),.10-.05*math.sin(a)))
for j in range(1,21):centers.append((cx-.10,.10+.10*j/20))
for j in range(1,49):
 a=math.pi*j/48;centers.append((cx-.15+.05*math.cos(a),.20+.05*math.sin(a)))
for j in range(1,31):centers.append((cx-.20,.20-.18*j/30))
all_centers=[(cx,.125)]+centers
for j,(x,z) in enumerate(centers,1):
 prev=all_centers[j-1];nxt=all_centers[min(j+1,len(all_centers)-1)];tangent=Vector((nxt[0]-prev[0],0,nxt[1]-prev[1])).normalized();normal=Vector((-tangent.z,0,tangent.x));rr=[]
 for radius in [.025,.031]:rr.append([tuple(Vector((x,cy,z))+radius*(math.cos(2*math.pi*i/N)*normal+Vector((0,math.sin(2*math.pi*i/N),0)))) for i in range(N)])
 rings.append(rr)
verts=[q for ring in rings for wall in ring for q in wall];faces=[]
def ix(j,w,i):return j*2*N+w*N+(i%N)
for j in range(len(rings)-1):
 for w in range(2):
  for i in range(N):faces.append((ix(j,w,i),ix(j,w,i+1),ix(j+1,w,i+1),ix(j+1,w,i)))
for j in [0,len(rings)-1]:
 for i in range(N):faces.append((ix(j,0,i),ix(j,1,i),ix(j,1,i+1),ix(j,0,i+1)))
me=bpy.data.meshes.new('WC109_continuous_hollow_S_trap');me.from_pydata(verts,[],faces);me.materials.append(original.data.materials[0]);bm=bmesh.new();bm.from_mesh(me);bmesh.ops.recalc_face_normals(bm,faces=bm.faces);nonmanifold=sum(not e.is_manifold for e in bm.edges);assert nonmanifold==0;bm.to_mesh(me);bm.free()
for f in me.polygons:f.use_smooth=True
trap=bpy.data.objects.new(me.name,me);bpy.context.scene.collection.objects.link(trap);trap['scope']='Prototype hydraulic interior extension, not a validated complete sanitary product.'
assert min(v.co.z for v in me.vertices)>0 and max(v.co.z for v in me.vertices)<.385
bpy.ops.wm.save_as_mainfile(filepath=str(p/'candidate.blend'));assert hashlib.sha256(src.read_bytes()).hexdigest()==source_sha
views=[{'name':'wc109_bowl_oblique','location':[.4,-.4,1.2],'target':[.02,0,.30],'hfov':45,'render_width':960,'samples':48},{'name':'wc109_waste_neck_top','location':[.02,0,.70],'target':[cx,0,.15],'hfov':48,'render_width':1280,'samples':48}];(p/'views.json').write_text(json.dumps(views,indent=2));(p/'build.json').write_text(json.dumps({'source':str(src),'source_sha256':source_sha,'ring_count':len(rings),'circumference_samples':N,'faces':len(faces),'nonmanifold_wall_edges':nonmanifold,'wall_m':.006,'bore_diameter_m':.05,'bend_center_radius_m':.05,'closed_wall_open_flow_inlet_outlet':True,'water_surface_added':False,'native_body_scale_or_geometry_changed':False,'room_integration':False,'limitations':['Prototype only. Connection overlap and collision with original pedestal/back cavities not yet validated.','No plumbing/hydraulic compliance claim or water seal calibration.','Closed wall topology is not photo acceptance or no self-intersection proof.']},indent=2));print('WC109_OPEN_TRAP_PILOT_SAVED')
