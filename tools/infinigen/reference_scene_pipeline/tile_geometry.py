"""Actual clipped tile solids, recessed grout and submillimetre bevels."""
import math
from collections import defaultdict
import bpy
import bmesh
from mathutils import Vector
from shapely.geometry import Polygon,box
from shapely.ops import unary_union,triangulate


def projected_floor(obj):
    polygons=[]
    for face in obj.data.polygons:
        pts=[obj.matrix_world@obj.data.vertices[i].co for i in face.vertices]
        normal=(pts[1]-pts[0]).cross(pts[2]-pts[0])
        if normal.length and abs(normal.z)/normal.length>.9:
            p=Polygon([(v.x,v.y) for v in pts])
            if p.is_valid and p.area>1e-8:polygons.append(p)
    return unary_union(polygons)


def pieces(shape):
    if shape.is_empty:return []
    return [shape] if shape.geom_type=='Polygon' else [p for p in shape.geoms if p.geom_type=='Polygon']


def tile_solid(name,poly,point,normal,material,owner):
    # Triangulated front/back retains clipped opening holes; perimeter sides
    # remain separate from real grout. All coordinates are world metres.
    xy=list(poly.exterior.coords)[:-1];verts=[];faces=[]
    for depth in (-.004,0):verts.extend([tuple(point(u,v)+normal*depth) for u,v in xy])
    lookup={tuple(round(x,8) for x in uv):i for i,uv in enumerate(xy)};n=len(xy)
    for tri in triangulate(poly):
        if not poly.covers(tri):continue
        ids=[lookup[tuple(round(x,8) for x in uv)] for uv in list(tri.exterior.coords)[:-1]]
        faces.append(tuple(i+n for i in ids));faces.append(tuple(reversed(ids)))
    for i in range(n):faces.append((i,(i+1)%n,(i+1)%n+n,i+n))
    me=bpy.data.meshes.new(name);me.from_pydata(verts,[],faces);me.materials.append(material);me.update();bm=bmesh.new();bm.from_mesh(me);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(me);bm.free()
    ob=bpy.data.objects.new(name,me);bpy.context.scene.collection.objects.link(ob);ob['reference_scene_owner']=owner;ob['program_key']=name;ob['audit_kind']='architecture'
    bevel=ob.modifiers.new('physical_tile_edge_radius','BEVEL');bevel.width=.00065;bevel.segments=3;bevel.limit_method='ANGLE'
    weighted=ob.modifiers.new('tile_weighted_normals','WEIGHTED_NORMAL');weighted.keep_sharp=True
    return ob


def grids(domain,size=.6,gap=.003):
    x0,y0,x1,y1=domain.bounds
    for i in range(math.floor(x0/size),math.ceil(x1/size)):
        for j in range(math.floor(y0/size),math.ceil(y1/size)):
            clipped=domain.intersection(box(i*size+gap/2,j*size+gap/2,(i+1)*size-gap/2,(j+1)*size-gap/2))
            for poly in pieces(clipped):
                if poly.area>1e-5 and not poly.interiors:yield poly


def apply(room_id,owner,floor_mat,wall_mat,grout):
    floor=bpy.data.objects[room_id+'.floor'];wall=bpy.data.objects[room_id+'.wall'];domain=projected_floor(floor);center=domain.representative_point();fz=max((floor.matrix_world@v.co).z for v in floor.data.vertices)
    floor_count=wall_count=0
    for poly in grids(domain):
        tile_solid(f'Realism_{room_id}_floor_tile_{floor_count}',poly,lambda u,v:Vector((u,v,fz)),Vector((0,0,1)),floor_mat,owner);floor_count+=1
    # Base mesh is the actual grout bed, 1.5mm below the tile surface.
    inv=floor.matrix_world.inverted()
    for vertex in floor.data.vertices:
        p=floor.matrix_world@vertex.co
        if abs(p.z-fz)<1e-5:p.z-=.0015;vertex.co=inv@p
    floor.data.materials.clear();floor.data.materials.append(grout);floor.data.update()
    planes=defaultdict(list)
    for face in wall.data.polygons:
        pts=[wall.matrix_world@wall.data.vertices[i].co for i in face.vertices]
        normal=(pts[1]-pts[0]).cross(pts[2]-pts[0])
        if normal.length<1e-8:continue
        normal.normalize()
        if abs(normal.z)>.1 or max(abs(normal.x),abs(normal.y))<.99:continue
        axis=0 if abs(normal.x)>.99 else 1;other=1-axis;mid=sum(pts,Vector())/len(pts)
        if normal.x*(center.x-mid.x)+normal.y*(center.y-mid.y)<=0:continue
        p=Polygon([(v[other],v.z) for v in pts])
        if p.is_valid and p.area>1e-7:planes[(axis,round(mid[axis],5),1 if normal[axis]>0 else -1)].append(p)
    for (axis,plane,sign),polys in planes.items():
        normal=Vector((sign,0,0) if axis==0 else (0,sign,0));surface=unary_union(polys)
        def point(u,v):return Vector((plane,u,v) if axis==0 else (u,plane,v))
        for poly in grids(surface):
            # Wall backing stays the grout surface; tile face is 1.5mm proud.
            tile_solid(f'Realism_{room_id}_wall_tile_{wall_count}',poly,lambda u,v:point(u,v)+normal*.0015,normal,wall_mat,owner);wall_count+=1
    wall.data.materials.clear();wall.data.materials.append(grout)
    return {'room':room_id,'floor_tiles':floor_count,'wall_tiles':wall_count,'tile_size_m':.6,'grout_width_m':.003,'grout_depth_m':.0015,'edge_radius_m':.00065}
