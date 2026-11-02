"""Exact native compact-body prototype contract, separate from standard WC dimensions."""
import array,hashlib,json
from pathlib import Path

def mesh_geometry_hash(mesh):
 co=array.array('f',[0])*(3*len(mesh.vertices));mesh.vertices.foreach_get('co',co)
 loops=array.array('I',[0])*len(mesh.loops);mesh.loops.foreach_get('vertex_index',loops)
 counts=array.array('I',[0])*len(mesh.polygons);mesh.polygons.foreach_get('loop_total',counts)
 return hashlib.sha256(co.tobytes()+loops.tobytes()+counts.tobytes()).hexdigest()

def verify_compact_body(obj,reference):
 contract=json.loads((Path(reference)/'native_compact_wc_studio73/geometry_contract.json').read_text())
 source=Path(contract['prototype_source'])
 if hashlib.sha256(source.read_bytes()).hexdigest()!=contract['prototype_source_sha256']:return {'pass':False,'reason':'stale compact prototype'}
 good=(obj.get('wc_variant')=='native_concealed_cistern' and obj.get('wc_compact_prototype_sha256')==contract['prototype_source_sha256'] and mesh_geometry_hash(obj.data)==contract['mesh_geometry_sha256'])
 return {'pass':good,'prototype_source_sha256':contract['prototype_source_sha256'],'geometry_matches_exact_native_prototype':good,'expected_depth_m':contract['depth_m'],'visual_trial_only':True,'scope':'Exact body geometry identity;not plumbing,door clearance orphotorealism certification.'}

def verify_compact_flush(obj,reference):
 import bpy
 from mathutils import Vector,Matrix
 from mathutils.bvhtree import BVHTree
 from wc_layout_checks import bounds,evaluated_geometry
 contract=json.loads((Path(reference)/'native_compact_wc_studio73/geometry_contract.json').read_text());errors=[];key=obj['program_key'];parts=[p for p in bpy.data.objects if p.get('wc_flush_parent_key')==key];by_name={p.get('wc_flush_part_source'):p for p in parts};expected={p['name'] for p in contract['plate_parts']}
 if len(parts)!=4 or set(by_name)!=expected:return {'pass':False,'errors':['Expected exact4 compact flush parts']}
 wall=bpy.data.objects.get(str(obj.get('wc_flush_wall_object','')))
 if wall is None or wall.type!='MESH':return {'pass':False,'errors':['Missing actual wall mesh']}
 lo,hi=bounds(obj);cx=(lo.x+hi.x)/2;ev,me,pts=evaluated_geometry(wall);tree=BVHTree.FromPolygons(pts,[tuple(f.vertices) for f in me.polygons]);ev.to_mesh_clear();origin=Vector((cx,hi.y+.0005,lo.z+1.18));hit,normal,index,d=tree.ray_cast(origin,Vector((0,1,0)),.5)
 if hit is None or normal.dot(Vector((0,1,0)))>-.8:return {'pass':False,'errors':['No independent inward wall ray hit']}
 M=Matrix.Translation(Vector((cx,hit.y,lo.z)))@Matrix.Rotation(-1.5707963267948966,4,'Z')
 for row in contract['plate_parts']:
  part=by_name[row['name']];expected_matrix=M@Matrix(row['matrix_world']);delta=max(abs(part.matrix_world[i][j]-expected_matrix[i][j]) for i in range(4) for j in range(4))
  if mesh_geometry_hash(part.data)!=row['mesh_geometry_sha256']:errors.append(row['name']+': mesh mismatch')
  if delta>3e-5:errors.append(row['name']+': detached ormisplaced relative tomeasured wall')
 for dx in [-.09,.09]:
  h,n,i,d=tree.ray_cast(origin+Vector((dx,0,0)),Vector((0,1,0)),.5)
  if h is None or abs(h.y-hit.y)>.0002:errors.append('Flush plate footprint lacks continuous measured wall support')
 return {'pass':not errors,'errors':errors,'actual_wall':wall.name,'measured_wall_point':list(hit),'parts':[p.name for p in parts],'scope':'Exact4 part geometries/transforms and3 independent wall rays;no cistern internals orhydraulic certification.'}
