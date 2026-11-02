"""Cut apertures in native open shell meshes without Boolean-generated caps."""
import bmesh
from mathutils import Vector


def remove_box_faces(obj,center,size):
    bm=bmesh.new();bm.from_mesh(obj.data)
    matrix=obj.matrix_world.copy();inverse=matrix.inverted()
    bmesh.ops.transform(bm,matrix=matrix,verts=list(bm.verts))
    lo=[center[i]-size[i]/2 for i in range(3)]
    hi=[center[i]+size[i]/2 for i in range(3)]
    for axis in range(3):
        for value in (lo[axis],hi[axis]):
            point=[0.,0.,0.];point[axis]=value
            normal=[0.,0.,0.];normal[axis]=1
            bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),
                dist=1e-6,plane_co=Vector(point),plane_no=Vector(normal),
                clear_inner=False,clear_outer=False)
    faces=[f for f in bm.faces if all(lo[i]+1e-5<f.calc_center_median()[i]<hi[i]-1e-5 for i in range(3))]
    count=len(faces)
    if faces:bmesh.ops.delete(bm,geom=faces,context='FACES')
    bmesh.ops.transform(bm,matrix=inverse,verts=list(bm.verts))
    bm.to_mesh(obj.data);bm.free();obj.data.update()
    return count
