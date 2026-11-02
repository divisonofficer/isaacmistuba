"""Saved native geometry/UV/optics and actual sofa-contact checks for98."""
import bpy,json,hashlib,sys,numpy as np
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from shader_optical_signature import optical_signature
revision=int(sys.argv[sys.argv.index('--')+1]) if '--' in sys.argv else 98
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';meta=json.loads((D/f'realism_refinement_r{revision}.json').read_text());row=meta['actual_pillows'];sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();out=D/f'actual_pillows_saved_audit_r{revision}.json';assert not out.exists();assert sha(meta['candidate'])==meta['candidate_sha256'];assert sha(row['prototype'])==row['prototype_sha256']
def geom(mesh):
 h=hashlib.sha256()
 for col,field,n,dtype in [(mesh.vertices,'co',len(mesh.vertices)*3,np.float32),(mesh.loops,'vertex_index',len(mesh.loops),np.int32),(mesh.polygons,'loop_total',len(mesh.polygons),np.int32)]:
  a=np.empty(n,dtype=dtype);col.foreach_get(field,a);h.update(a.tobytes())
 for uv in mesh.uv_layers:
  a=np.empty(len(uv.data)*2,np.float32);uv.data.foreach_get('uv',a);h.update(a.tobytes())
 return h.hexdigest()
bpy.ops.wm.open_mainfile(filepath=row['prototype']);native={}
for rec in row['records']:
 o=bpy.data.objects[rec['prototype_object']];m=o.matrix_world.to_3x3();native[rec['prototype_object']]={'geometry':geom(o.data),'optics':[optical_signature(mat) for mat in o.data.materials],'gram':m.transposed()@m}
bpy.ops.wm.open_mainfile(filepath=meta['candidate']);errors=[];records=[]
for name in row['removed_owned_objects']:
 if name in bpy.context.scene.objects:errors.append('Old pillow part remains:'+name)
for rec in row['records']:
 o=bpy.data.objects[rec['object']];source=native[rec['prototype_object']];m=o.matrix_world.to_3x3();gram=m.transposed()@m
 if geom(o.data)!=source['geometry']:errors.append(o.name+':native_geometry_uv')
 if [optical_signature(mat) for mat in o.data.materials]!=source['optics']:errors.append(o.name+':optics')
 if max(abs(gram[i][j]-source['gram'][i][j]) for i in range(3) for j in range(3))>1e-5:errors.append(o.name+':nonrigid_scale')
 sofa=bpy.data.objects[rec['sofa']];world=[sofa.matrix_world@v.co for v in sofa.data.vertices];lo=Vector([min(p[k] for p in world) for k in range(3)]);nm=sofa.matrix_world.to_3x3().inverted().transposed();sf=[];bf=[]
 for f in sofa.data.polygons:
  n=(nm@f.normal).normalized();c=sofa.matrix_world@f.center
  if n.z>.35 and lo.z+.25<c.z<lo.z+.65 and c.x>lo.x+.25:sf.append(tuple(f.vertices))
  if n.x>.3 and c.z>lo.z+.4 and c.x<lo.x+.6:bf.append(tuple(f.vertices))
 seat=BVHTree.FromPolygons(world,sf);back=BVHTree.FromPolygons(world,bf);whole=BVHTree.FromPolygons(world,[tuple(f.vertices) for f in sofa.data.polygons]);pts=[o.matrix_world@v.co for v in o.data.vertices];own=BVHTree.FromPolygons(pts,[tuple(f.vertices) for f in o.data.polygons]);counts={k:len(own.overlap(t)) for k,t in [('seat',seat),('back',back),('whole_sofa',whole)]};gaps={k:min(t.find_nearest(p)[3] for p in pts) for k,t in [('seat',seat),('back',back)]}
 if any(counts.values()) or max(gaps.values())>.003:errors.append(o.name+':support_contact')
 if o.parent!=sofa:errors.append(o.name+':parent')
 records.append({'object':o.name,'native_geometry_uv_sha256':source['geometry'],'surface_overlaps':counts,'minimum_vertex_gaps_m':gaps})
out.write_text(json.dumps({'source':meta['candidate'],'source_sha256':sha(meta['candidate']),'records':records,'errors':errors,'pass':not errors,'photorealism_accepted':False,'scope':'Exact native mesh/UV/declared studio optics,rigidscale,old owned-part absence,seat/back/whole-sofa triangle surface separation and nearest vertex contact. Not closedvolume/full furniture interactions,cloth simulation or photo acceptance.'},indent=2));assert not errors,errors
