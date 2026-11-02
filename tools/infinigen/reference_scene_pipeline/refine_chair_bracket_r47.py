"""Separate the rear timber termination from upholstery and bridge it with fitted mounting hardware."""
import bpy,bmesh,json,hashlib,math
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r46.blend';out=base/'scene_candidate_r47.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
metal=bpy.data.materials.new('R47_brushed_mounting_steel');metal.use_nodes=True;bs=metal.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(.24,.25,.26,1);bs.inputs['Metallic'].default_value=1;bs.inputs['Roughness'].default_value=.28

def tree(o):return BVHTree.FromPolygons([v.co.copy() for v in o.data.vertices],[list(f.vertices) for f in o.data.polygons])
def child(parent,key,mesh,mat,bevel=0):
 bm=bmesh.new();bm.from_mesh(mesh);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(mesh);bm.free();mesh.materials.append(mat);o=bpy.data.objects.new('R47_'+key,mesh);bpy.context.scene.collection.objects.link(o);o.parent=parent;o['program_key']=key;o['reference_scene_owner']='commercial_office_floor_02';o['audit_kind']='detail'
 if bevel:mod=o.modifiers.new('Machined edge radius','BEVEL');mod.width=bevel;mod.segments=3
 return o

def box(parent,key,lo,hi):
 bm=bmesh.new();bmesh.ops.create_cube(bm,size=1);bmesh.ops.scale(bm,vec=Vector(hi)-Vector(lo),verts=bm.verts);bmesh.ops.translate(bm,vec=(Vector(hi)+Vector(lo))/2,verts=bm.verts);mesh=bpy.data.meshes.new(key);bm.to_mesh(mesh);bm.free();return child(parent,key,mesh,metal,.001)
for parent in list(bpy.data.objects):
 key=parent.get('program_key','')
 if parent.type!='MESH' or not key.startswith('breakout_chair') or parent.parent is not None:continue
 back=next(o for o in parent.children if o.get('program_key')==key+'_back_upholstery');backtree=tree(back);parts=[]
 for side,sign in enumerate([-1,1]):
  post=next(o for o in parent.children if o.get('program_key')==key+f'_continuous_rear_stile_{side}');post.data=post.data.copy()
  for v in post.data.vertices:
   t=max(0,min(1,(v.co.z-.40)/.23));v.co.x-=.09*t*t*(3-2*t)
  for uv in post.data.uv_layers.active.data:uv.uv.x*=.10
  post.data.update();z=.60;t=(z-.38)/.27;s=t*t*(3-2*t);yc=sign*(.20-.055*s);u=max(0,min(1,(z-.40)/.23));cx=-.20-.09*u*u*(3-2*u);hit,_,_,_=backtree.ray_cast(Vector((-1,yc,z)),Vector((1,0,0)),2);assert hit is not None;gap=hit.x-(cx+.016);assert .025<gap<.13,gap
  # Fitted steel plate follows the actual upholstered back, with 1mm deliberate embedding.
  verts=[];nx=6;nz=8
  for layer in [0,1]:
   for j in range(nz+1):
    zz=z-.027+.054*j/nz
    for k in range(nx+1):
     yy=yc-.018+.036*k/nx;q,_,_,_=backtree.ray_cast(Vector((-1,yy,zz)),Vector((1,0,0)),2);assert q is not None;verts.append((q.x+(.001 if layer else -.004),yy,zz))
  faces=[];stride=(nx+1)*(nz+1)
  for j in range(nz):
   for k in range(nx):
    i=j*(nx+1)+k;faces.extend([(i,i+1,i+nx+2,i+nx+1),(stride+i+nx+1,stride+i+nx+2,stride+i+1,stride+i)])
  perimeter=list(range(nx+1))+[j*(nx+1)+nx for j in range(1,nz+1)]+[nz*(nx+1)+k for k in range(nx-1,-1,-1)]+[j*(nx+1) for j in range(nz-1,0,-1)]
  for i,j in zip(perimeter,perimeter[1:]+perimeter[:1]):faces.append((i,j,stride+j,stride+i))
  mesh=bpy.data.meshes.new('Conforming_back_mount');mesh.from_pydata(verts,[],faces);plate=child(parent,key+f'_back_mount_{side}',mesh,metal,.0005);bridge=box(parent,key+f'_back_bridge_{side}',(cx-.004,yc-.012,z-.009),(hit.x-.002,yc+.012,z+.009));posttree=tree(post);bridgetree=tree(bridge);contacts={'bridge_post_pairs':len(bridgetree.overlap(posttree)),'bridge_plate_pairs':len(bridgetree.overlap(tree(plate))),'plate_back_pairs':len(tree(plate).overlap(backtree))};assert all(v>0 for v in contacts.values()),contacts
  for bolt,dz in enumerate([-.017,.017]):
   q,_,_,_=backtree.ray_cast(Vector((-1,yc,z+dz)),Vector((1,0,0)),2);bm=bmesh.new();bmesh.ops.create_cone(bm,cap_ends=True,cap_tris=False,segments=16,radius1=.003,radius2=.003,depth=.002);bmesh.ops.transform(bm,matrix=Matrix.Rotation(math.pi/2,4,'Y'),verts=bm.verts);bmesh.ops.translate(bm,vec=Vector((q.x-.005,yc,z+dz)),verts=bm.verts);mesh=bpy.data.meshes.new('Mount_fastener_head');bm.to_mesh(mesh);bm.free();child(parent,key+f'_mount_fastener_{side}_{bolt}',mesh,metal,.0003)
  parts.append({'post':post.name,'rearward_maximum_offset_m':.09,'wood_uv_U_multiplier':.10,'bridge_gap_m':gap,'mount_dimensions_yz_m':[.036,.054],'surface_intersections':contacts,'note':'Explicit visible bridge and fitted plate replace timber/fabric termination overlap.'})
 rows.append({'chair':key,'mounts':parts})
assert len(rows)==4;bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r47.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'scope':'rear timber bend/UV andactual metal mounting interface;upholstery,room transforms,lighting unchanged','changes':rows,'photorealism_accepted':False,'requires':'same front/rear actual image comparison,physical regression,independent review'},indent=2));print('SAVED',out,flush=True)
