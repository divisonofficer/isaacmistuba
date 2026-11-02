"""Assemble cached Infinigen leaf/petiole components into a potted indoor plant trial."""
import bpy,json,math,numpy as np
from pathlib import Path
from mathutils import Vector,Euler
ROOT=Path(__file__).resolve().parents[3];ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
source=ref/'plant_library_banana_studio/bush.blend';out=ref/'assembled_leaf_plant_studio';assert not out.exists();out.mkdir()
bpy.ops.wm.open_mainfile(filepath=str(source));leaf=bpy.data.objects['ir_plant'];bpy.context.view_layer.update()
mesh=bpy.data.meshes.new_from_object(leaf.evaluated_get(bpy.context.evaluated_depsgraph_get()))
co=np.empty(len(mesh.vertices)*3,dtype=np.float32);mesh.vertices.foreach_get('co',co);co=co.reshape(-1,3)
M=np.asarray(leaf.matrix_world);world=co@M[:3,:3].T+M[:3,3]
root=np.median(world[world[:,2]<world[:,2].min()+.01],axis=0);height=world[:,2].max()-world[:,2].min()
unit=(world-root)/height;mesh.vertices.foreach_set('co',unit.astype(np.float32).ravel());mesh.update()
bpy.data.objects.remove(leaf,do_unlink=True);bpy.data.objects.remove(bpy.data.objects['Preview_pot_proxy'],do_unlink=True)
parts=[]
for i,(h,tilt,yaw) in enumerate([(1.55,18,0),(1.35,30,77),(1.65,10,147),(1.15,36,211),(1.45,24,267),(1.25,32,319),(1.05,40,33)]):
 o=bpy.data.objects.new('Indoor_leaf_'+str(i),mesh);bpy.context.scene.collection.objects.link(o);o.location=(.025*math.cos(i*2.4),.025*math.sin(i*2.4),.355);o.scale=(h,h,h);o.rotation_euler=Euler((math.radians(tilt),0,math.radians(yaw)),'XYZ');o['source_component']='plant_library_v2/plantbananatree_001.blend';parts.append(o)
N=96;profile=[(.175,0),(.235,.375),(.239,.390),(.236,.398),(.221,.398),(.217,.375),(.158,.025)]
verts=[(rad*math.cos(k*math.tau/N),rad*math.sin(k*math.tau/N),z) for rad,z in profile for k in range(N)]
faces=[(j*N+k,j*N+(k+1)%N,(j+1)*N+(k+1)%N,(j+1)*N+k) for j in range(len(profile)-1) for k in range(N)]
faces.extend([tuple(reversed(range(N))),tuple(range((len(profile)-1)*N,len(profile)*N))])
pm=bpy.data.meshes.new('Hollow_planter_mesh');pm.from_pydata(verts,[],faces);pm.materials.append(bpy.data.materials['Preview_ceramic'])
for f in pm.polygons:f.use_smooth=len(f.vertices)==4
pot=bpy.data.objects.new('Hollow_planter',pm);bpy.context.scene.collection.objects.link(pot)
bpy.ops.mesh.primitive_cylinder_add(vertices=96,radius=.214,depth=.025,location=(0,0,.350));soil=bpy.context.object;soil.name='Planter_soil'
sm=bpy.data.materials.new('Soil');sm.use_nodes=True;n=sm.node_tree.nodes;l=sm.node_tree.links;bs=n.get('Principled BSDF');bs.inputs['Base Color'].default_value=(.045,.025,.012,1);bs.inputs['Roughness'].default_value=.95
tc=n.new('ShaderNodeTexCoord');noise=n.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=150;l.new(tc.outputs['Object'],noise.inputs['Vector']);bump=n.new('ShaderNodeBump');bump.inputs['Distance'].default_value=.002;bump.inputs['Strength'].default_value=.35;l.new(noise.outputs['Fac'],bump.inputs['Height']);l.new(bump.outputs[0],bs.inputs['Normal']);soil.data.materials.append(sm)
bpy.context.view_layer.update();bounds=[o.matrix_world@Vector(c) for o in parts for c in o.bound_box];lo=[min(p[i] for p in bounds) for i in range(3)];hi=[max(p[i] for p in bounds) for i in range(3)]
bpy.ops.wm.save_as_mainfile(filepath=str(out/'plant.blend'));(out/'views.json').write_text(json.dumps([{'name':'assembled_plant','location':[3,-4,2.3],'target':[0,0,1.0],'hfov':42,'render_width':800,'samples':32}],indent=2))
(out/'provenance.json').write_text(json.dumps({'component':'data/plant_library_v2/plantbananatree_001.blend','assembly':'Seven shared-mesh native leaf/petiole components,deterministic height/tilt/yaw;hollow ceramic planter andsoil','leaf_count':len(parts),'leaf_bounds_m':[lo,hi],'photorealism_accepted':False,'requires':'Actual preview;pot/root support and room canopy clearance before any integration'},indent=2));print('SAVED',out,lo,hi,flush=True)
