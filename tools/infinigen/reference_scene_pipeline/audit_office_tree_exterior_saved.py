"""Saved tree native geometry/UV/isometry and actual grade-contact audit."""
import bpy,json,sys,hashlib,numpy as np
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';meta=json.loads((D/'realism_refinement_r103.json').read_text());row=meta['exterior_trees'];out=D/'exterior_trees_saved_audit_r103.json';assert not out.exists()
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();assert sha(meta['candidate'])==meta['candidate_sha256'];assert sha(row['prototype_blend'])==row['prototype_sha256']
def geom(mesh):
 h=hashlib.sha256()
 for col,field,n,dtype in [(mesh.vertices,'co',len(mesh.vertices)*3,np.float32),(mesh.loops,'vertex_index',len(mesh.loops),np.int32),(mesh.polygons,'loop_total',len(mesh.polygons),np.int32)]:
  a=np.empty(n,dtype=dtype);col.foreach_get(field,a);h.update(a.tobytes())
 for uv in mesh.uv_layers:
  a=np.empty(len(uv.data)*2,np.float32);uv.data.foreach_get('uv',a);h.update(a.tobytes())
 return h.hexdigest()
bpy.ops.wm.open_mainfile(filepath=row['prototype_blend']);original=bpy.data.objects[row['asset']['objects'][0]];wanted=geom(original.data);native_faces=len(original.data.polygons);native_basis=original.matrix_world.to_3x3();wanted_gram=native_basis.transposed()@native_basis
bpy.ops.wm.open_mainfile(filepath=meta['candidate']);errors=[];records=[];grade=bpy.data.objects[row['grade_object']];tree=BVHTree.FromPolygons([grade.matrix_world@v.co for v in grade.data.vertices],[tuple(f.vertices) for f in grade.data.polygons]);mesh_hashes={};data_ids=set()
for record in row['records']:
 o=bpy.data.objects[record['object']];data_ids.add(o.data.name)
 if o.data.name not in mesh_hashes:mesh_hashes[o.data.name]=geom(o.data)
 basis=o.matrix_world.to_3x3();gram=basis.transposed()@basis
 if mesh_hashes[o.data.name]!=wanted or len(o.data.polygons)!=native_faces:errors.append(o.name+':native_geometry_uv')
 if max(abs(gram[i][j]-wanted_gram[i][j]) for i in range(3) for j in range(3))>1e-5:errors.append(o.name+':scale_shear')
 pts=[o.matrix_world@Vector(v) for v in o.bound_box];lo=[min(p[k] for p in pts) for k in range(3)];hi=[max(p[k] for p in pts) for k in range(3)]
 if not(hi[0]<-.5 or lo[0]>16.5 or hi[1]<-.5 or lo[1]>22.5):errors.append(o.name+':office_envelope')
 # Rotation is aroundZ, so lowest local native vertex gives actual root grade contact.
 zrow=o.matrix_world[2];v=min(o.data.vertices,key=lambda v:zrow[0]*v.co.x+zrow[1]*v.co.y+zrow[2]*v.co.z)
 foot=o.matrix_world@v.co;hit=tree.ray_cast(foot+Vector((0,0,.1)),Vector((0,0,-1)),.2)[0];gap=None if hit is None else foot.z-hit.z
 if gap is None or abs(gap)>.0001:errors.append(o.name+':grade_contact')
 records.append({'object':o.name,'root_grade_gap_m':gap,'bounds_lo':lo,'bounds_hi':hi})
if len(data_ids)!=1:errors.append('Tree instances do not share one native mesh')
images=[]
for mat in bpy.data.objects[row['records'][0]['object']].data.materials:
 if not mat or not mat.use_nodes:continue
 for n in mat.node_tree.nodes:
  if n.type=='TEX_IMAGE' and n.image:
   images.append({'material':mat.name,'image':n.image.name,'packed':bool(n.image.packed_file)})
   if not n.image.packed_file:errors.append('Unpacked tree image')
out.write_text(json.dumps({'source':meta['candidate'],'source_sha256':sha(meta['candidate']),'native_geometry_uv_sha256':wanted,'unique_tree_meshes':len(data_ids),'native_faces_per_tree':native_faces,'instances':records,'images':images,'errors':errors,'pass':not errors,'photorealism_accepted':False,'scope':'12native-scale rigid tree instances,exact source mesh/UV hash,office-envelope separation,actual lowest-root-point contact with grade and packed maps. No complete trunk/root containment,structural anchoring,city/reference or photorealism acceptance.'},indent=2));assert not errors,errors
