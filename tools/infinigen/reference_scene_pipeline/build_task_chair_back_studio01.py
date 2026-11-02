"""Native task-chair base with replacement curved mesh back; prototype only."""
import bpy,bmesh,math,json
from pathlib import Path
from mathutils import Matrix,Vector
r=Path('/jarvis/project/robomituba');ref=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';out=ref/'task_chair_back_studio01';assert not out.exists();out.mkdir();bpy.ops.wm.read_factory_settings(use_empty=True)
name='Office02_pod_0_0_chair0_TaskChairFactory(19).spawn_asset(19)'
with bpy.data.libraries.load(str(r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r62.blend'),link=False) as (a,b):b.objects=[name]
old=b.objects[0];bpy.context.scene.collection.objects.link(old);old.parent=None;old.matrix_world=Matrix.Identity(4);old.location.y=1.1
new=old.copy();new.data=old.data.copy();bpy.context.scene.collection.objects.link(new);new.location.y=-1.1;new.name='Prototype_native_base_curved_back'
bm=bmesh.new();bm.from_mesh(new.data);faces=[f for f in bm.faces if f.material_index==3];assert faces;removed_face_count=len(faces);bmesh.ops.delete(bm,geom=faces,context='FACES');loose=[v for v in bm.verts if not v.link_faces]
if loose:bmesh.ops.delete(bm,geom=loose,context='VERTS')
bm.to_mesh(new.data);bm.free()
def mat(name,color,rough):
 m=bpy.data.materials.new(name);m.use_nodes=True;p=m.node_tree.nodes['Principled BSDF'];p.inputs['Base Color'].default_value=(*color,1);p.inputs['Roughness'].default_value=rough;return m
plastic=mat('Prototype_black_polymer',(.018,.020,.023),.42)
def xpos(z):return -.27+.035*math.exp(-((z-.74)/.14)**2)-.04*(z-.88)
def signed(v):return math.copysign(abs(v)**.4,v)
points=[]
for i in range(96):
 t=2*math.pi*i/96;y=.225*signed(math.cos(t));z=.88+.28*signed(math.sin(t));points.append((xpos(z),y,z))
c=bpy.data.curves.new('Curved back perimeter','CURVE');c.dimensions='3D';c.bevel_depth=.012;c.bevel_resolution=3;s=c.splines.new('POLY');s.points.add(len(points)-1)
for p,co in zip(s.points,points):p.co=(*co,1)
s.use_cyclic_u=True;o=bpy.data.objects.new('Rounded curved back frame',c);bpy.context.scene.collection.objects.link(o);o.location.y=-1.1;c.materials.append(plastic)
verts=[(xpos(.88),0,.88)];faces=[];N=96;R=16
for k in range(1,R+1):
 for i in range(N):
  t=2*math.pi*i/N;y=.212*k/R*signed(math.cos(t));z=.88+.267*k/R*signed(math.sin(t));verts.append((xpos(z),y,z))
for i in range(N):faces.append((0,1+i,1+(i+1)%N))
for k in range(R-1):
 a=1+k*N;b=a+N
 for i in range(N):j=(i+1)%N;faces.append((a+i,b+i,b+j,a+j))
mesh=bpy.data.meshes.new('Curved fine mesh surface');mesh.from_pydata(verts,[],faces);mesh.update()
for f in mesh.polygons:f.use_smooth=True
o=bpy.data.objects.new('Curved mesh back',mesh);bpy.context.scene.collection.objects.link(o);o.location.y=-1.1
m=mat('Fine woven back dielectric',(.022,.025,.028),.65);mesh.materials.append(m);nt=m.node_tree;p=nt.nodes['Principled BSDF'];tex=nt.nodes.new('ShaderNodeTexCoord');waves=[]
for direction in ['Y','Z']:
 w=nt.nodes.new('ShaderNodeTexWave');w.bands_direction=direction;w.inputs['Scale'].default_value=180;nt.links.new(tex.outputs['Object'],w.inputs['Vector']);gt=nt.nodes.new('ShaderNodeMath');gt.operation='GREATER_THAN';gt.inputs[1].default_value=.55;nt.links.new(w.outputs['Fac'],gt.inputs[0]);waves.append(gt)
mx=nt.nodes.new('ShaderNodeMath');mx.operation='MAXIMUM'
for i,w in enumerate(waves):nt.links.new(w.outputs[0],mx.inputs[i])
nt.links.new(mx.outputs[0],p.inputs['Alpha']);bump=nt.nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.15;bump.inputs['Distance'].default_value=.00025;nt.links.new(mx.outputs[0],bump.inputs['Height']);nt.links.new(bump.outputs[0],p.inputs['Normal'])
bpy.ops.mesh.primitive_plane_add(size=200);g=bpy.context.object;g.data.materials.append(mat('Studio floor',(.22,.22,.22),.7))
w=bpy.data.worlds.new('Studio');w.use_nodes=True;w.node_tree.nodes['Background'].inputs['Strength'].default_value=.22;bpy.context.scene.world=w
for name,loc,power,size in [('Key',(-2,-3,3),400,2),('Fill',(2,2,2),200,2)]:
 d=bpy.data.lights.new(name,'AREA');d.energy=power;d.size=size;o=bpy.data.objects.new(name,d);bpy.context.scene.collection.objects.link(o);o.location=loc;o.rotation_euler=(Vector((0,0,.6))-o.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.wm.save_as_mainfile(filepath=str(out/'studio.blend'))
views=[]
for name,y in [('baseline',1.1),('curved_back',-1.1)]:views.append({'name':name,'location':[-1.7,y-1.1,1.25],'target':[0,y,.68],'hfov':42,'render_width':768,'samples':32})
(out/'views.json').write_text(json.dumps(views,indent=2));(out/'provenance.json').write_text(json.dumps({'source':'scene_candidate_r62.blend','source_object':old.name,'change':'only source slot3 back primitives replaced by rounded curved frame and alpha-woven surface; native seat/base retained','removed_original_back_faces':removed_face_count,'scope':'prototype only; no room integration/support pass/visual acceptance'},indent=2));print(out,flush=True)
