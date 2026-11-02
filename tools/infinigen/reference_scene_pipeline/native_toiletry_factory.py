"""Native Infinigen spin-based bottle body/cap with a toiletries profile and measured fitted label.
Experimental until scene-level visual/physical review; no brand textures or room edits.
"""
import bpy,math,sys
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'modules/infinigen'))
from infinigen.assets.objects.tableware.bottle import BottleFactory

def material(name,color,rough):
 m=bpy.data.materials.new(name);m.use_nodes=True;p=m.node_tree.nodes.get('Principled BSDF');p.inputs['Base Color'].default_value=(*color,1);p.inputs['Roughness'].default_value=rough;p.inputs['IOR'].default_value=1.46;return m

def mesh(name,verts,faces,mat):
 me=bpy.data.meshes.new(name);me.from_pydata(verts,[],faces);me.update();o=bpy.data.objects.new(name,me);bpy.context.collection.objects.link(o);me.materials.append(mat);return o

def create_toiletry(seed,height,radius,color):
 f=BottleFactory(seed);f.z_length=height;f.x_length=radius;f.x_cap=.72;f.z_cap=.08;f.z_neck=.72;f.z_waist=0;f.bottle_width=.0012
 f.x_anchors=[0,.90,1,1,.96,.78,.72,.72,0];f.z_anchors=[0,0,.02,.72,.76,.80,.82,1,1];f.is_vector=[0,1,0,1,0,0,1,1,0]
 bodymat=material(f'ToiletryNative_body_{seed}',color,.30);capmat=material(f'ToiletryNative_cap_{seed}',(.065,.072,.07),.42);papermat=material(f'ToiletryNative_label_{seed}',(.82,.80,.73),.6);f.surface=bodymat;f.cap_surface=capmat;f.cap_subsurf=True # Native helper selects SIMPLE subdivision, preserving the closure housing envelope.
 body=f.make_bottle();body.name=f'ToiletryNative_body_{seed}';cap=f.make_cap();cap.name=f'ToiletryNative_cap_{seed}'
 for p in body.data.polygons:p.use_smooth=True
 for p in cap.data.polygons:p.use_smooth=len(p.vertices)==4
 be=cap.modifiers.new('Molded cap edge radius','BEVEL');be.width=.00035;be.segments=3;be.limit_method='ANGLE'
 bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();ev=body.evaluated_get(deps);me=ev.to_mesh();points=[body.matrix_world@v.co for v in me.vertices];faces=[tuple(p.vertices) for p in me.polygons];tree=BVHTree.FromPolygons(points,faces);ev.to_mesh_clear();N=128;vertical_steps=64;label_offset=.00015;verts=[];distances=[]
 for row in range(vertical_steps+1):
  z=height*(.14+.46*row/vertical_steps)
  for k in range(N):
   a=math.tau*k/N;d=Vector((math.cos(a),math.sin(a),0));origin=d*.15;origin.z=z;hit,normal,index,dist=tree.ray_cast(origin,-d,.3);assert hit is not None,(seed,z,k);v=hit+normal*label_offset;verts.append(tuple(v));distances.append((v-hit).length)
 fs=[(j*N+k,j*N+(k+1)%N,(j+1)*N+(k+1)%N,(j+1)*N+k) for j in range(vertical_steps) for k in range(N)];label=mesh(f'ToiletryNative_fitted_label_{seed}',verts,fs,papermat)
 label_tree=BVHTree.FromPolygons([Vector(v) for v in verts],fs);overlaps=len(tree.overlap(label_tree));assert overlaps==0,('label/body intersections',seed,overlaps)
 for p in label.data.polygons:p.use_smooth=True
 # Thin closed lid and rear hinge above the existing native closure housing.
 capev=cap.evaluated_get(deps);cm=capev.to_mesh();cps=[cap.matrix_world@v.co for v in cm.vertices];top=max(v.z for v in cps);cr=max(math.hypot(v.x,v.y) for v in cps);capev.to_mesh_clear();lidverts=[]
 for z in [top+.0005,top+.0028]:
  for k in range(N):a=math.tau*k/N;lidverts.append((cr*math.cos(a),cr*math.sin(a),z))
 lidfaces=[tuple(reversed(range(N))),tuple(range(N,2*N))]+[(k,(k+1)%N,(k+1)%N+N,k+N) for k in range(N)];lid=mesh(f'ToiletryNative_flip_lid_{seed}',lidverts,lidfaces,capmat)
 for p in lid.data.polygons:p.use_smooth=len(p.vertices)==4
 be=lid.modifiers.new('Lid molded edge','BEVEL');be.width=.00035;be.segments=3;be.limit_method='ANGLE'
 bpy.ops.mesh.primitive_cube_add(size=1,location=(0,cr*.96,top+.0008));hinge=bpy.context.object;hinge.name=f'ToiletryNative_hinge_{seed}';hinge.dimensions=(.006,.0035,.004);bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);hinge.data.materials.append(capmat);be=hinge.modifiers.new('Hinge edge radius','BEVEL');be.width=.0006;be.segments=3
 objects=[body,cap,label,lid,hinge];assert max(abs(x-label_offset) for x in distances)<1e-8
 return objects,{'seed':seed,'engine':'BottleFactory.make_bottle/make_cap','profile':'short broad shoulder/neck,wide native closure housing+closed flip lid/hinge','body_height_m':height,'body_radius_m':radius,'label_surface_offset_m':label_offset,'label_body_triangle_overlap_count':overlaps,'label_vertical_steps':vertical_steps,'label_surface_ray_count':len(distances),'label_scope':'150micron fitted surface,thin label has intentional open boundary;no thick cylinder shell','factory_note':'Native spin andsubdivision retained;beverage profile andloose factory wrap replaced. No generic grocery mesh scaling.','fluid_or_hinge_simulation':False}
