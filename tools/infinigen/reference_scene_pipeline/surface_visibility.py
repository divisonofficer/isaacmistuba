"""Bounded opaque surface first-hit probes; not a renderer/occlusion certification."""
from mathutils import Vector
from mathutils.bvhtree import BVHTree
import bpy

def first_surface_hits(objects, rays):
    objects=[o for o in objects if o.type=='MESH' and not o.hide_render]
    cached={};results=[];dg=bpy.context.evaluated_depsgraph_get()
    for row in rays:
        origin=Vector(row['origin']);direction=Vector(row['direction']).normalized();limit=row['distance']
        end=origin+direction*limit;best=None
        for obj in objects:
            corners=[obj.matrix_world@Vector(v) for v in obj.bound_box]
            if any(max(p[k] for p in corners)<min(origin[k],end[k])-1e-5 or
                   min(p[k] for p in corners)>max(origin[k],end[k])+1e-5 for k in range(3)):continue
            if obj.name not in cached:
                ev=obj.evaluated_get(dg);mesh=ev.to_mesh()
                tree=BVHTree.FromPolygons([obj.matrix_world@v.co for v in mesh.vertices],
                                         [tuple(f.vertices) for f in mesh.polygons])
                materials=[mesh.materials[f.material_index].name if mesh.materials and mesh.materials[f.material_index] else None for f in mesh.polygons]
                cached[obj.name]=(tree,materials);ev.to_mesh_clear()
            tree,materials=cached[obj.name];point,normal,index,distance=tree.ray_cast(origin,direction,limit)
            if point is not None and (best is None or distance<best['distance_m']):
                best={'object':obj.name,'material':materials[index],'distance_m':distance,'point':list(point)}
        results.append({**row,'first_hit':best})
    return results
