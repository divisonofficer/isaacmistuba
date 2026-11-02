"""Small manufactured parts, explicit physical dimensions, flat cylinder caps."""
import bpy,math
from mathutils import Vector,Matrix
SCENE='commercial_office_floor_02'
def mark(o,key,kind='detail'):
 o['reference_scene_owner']=SCENE;o['program_key']=key;o['audit_kind']=kind;return o

def box(key,center,size,material,radius=.0005):
 signs=[(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)];faces=[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)];mesh=bpy.data.meshes.new(key);mesh.from_pydata([tuple(v[i]*size[i]/2 for i in range(3)) for v in signs],[],faces);mesh.materials.append(material);o=bpy.data.objects.new(key,mesh);bpy.context.scene.collection.objects.link(o);o.location=center
 if radius:mod=o.modifiers.new('Manufactured_radius','BEVEL');mod.width=radius;mod.segments=3;o.modifiers.new('Planar_normals','WEIGHTED_NORMAL')
 return mark(o,key)

def rod(key,start,end,radius,material,segments=48):
 start=Vector(start);end=Vector(end);axis=(end-start).normalized();u=axis.cross(Vector((1,0,0)) if abs(axis.x)<.8 else Vector((0,1,0))).normalized();v=axis.cross(u);vertices=[tuple(c+radius*(u*math.cos(math.tau*k/segments)+v*math.sin(math.tau*k/segments))) for c in [start,end] for k in range(segments)];faces=[(k,(k+1)%segments,segments+(k+1)%segments,segments+k) for k in range(segments)]+[tuple(reversed(range(segments))),tuple(range(segments,2*segments))];mesh=bpy.data.meshes.new(key);mesh.from_pydata(vertices,[],faces);mesh.materials.append(material)
 for f in mesh.polygons:f.use_smooth=len(f.vertices)==4
 o=bpy.data.objects.new(key,mesh);bpy.context.scene.collection.objects.link(o);return mark(o,key)

def tube(key,points,radius,material):
 data=bpy.data.curves.new(key,'CURVE');data.dimensions='3D';data.bevel_depth=radius;data.bevel_resolution=4;data.resolution_u=18;spl=data.splines.new('BEZIER');spl.bezier_points.add(len(points)-1)
 for p,co in zip(spl.bezier_points,points):p.co=co;p.handle_left_type='AUTO';p.handle_right_type='AUTO'
 data.materials.append(material);o=bpy.data.objects.new(key,data);bpy.context.scene.collection.objects.link(o);return mark(o,key)

def front_text(key,text,center,size,material):
 data=bpy.data.curves.new(key,'FONT');data.body=text;data.align_x='CENTER';data.align_y='CENTER';data.size=size;data.extrude=.00003;data.materials.append(material);o=bpy.data.objects.new(key,data);bpy.context.scene.collection.objects.link(o);o.location=center;o.rotation_euler=Matrix(((0,0,-1),(-1,0,0),(0,1,0))).to_euler();return mark(o,key)
