"""Exact11panel geometry,worldmetreUV,active native PBR and unchanged layout bindings."""
import bpy,json,hashlib
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';m=json.loads((D/'realism_refinement_r105.json').read_text());row=m['photographic_veneer'];out=D/'photographic_veneer_saved_audit_r105.json';assert not out.exists();sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();assert sha(m['candidate'])==m['candidate_sha256'];assert sha(m['source'])==m['source_sha256'];names={r['object'] for r in row['objects']}
def sig(o):return ([list(v) for v in o.matrix_world],o.type,o.data.name if o.data else None,[mat.name if mat else None for mat in o.data.materials] if o.type=='MESH' else [])
bpy.ops.wm.open_mainfile(filepath=m['source']);baseline={o.name:sig(o) for o in bpy.context.scene.objects};bpy.ops.wm.open_mainfile(filepath=m['candidate']);errors=[]
for name,expected in baseline.items():
 o=bpy.data.objects[name];actual=sig(o)
 if name not in names and actual!=expected:errors.append('Changed unrelated transform/data/binding:'+name)
 if name in names and actual[:2]!=expected[:2]:errors.append('Changed panel transform:'+name)
for rec in row['objects']:
 o=bpy.data.objects[rec['object']];mesh=o.data;geom=hashlib.sha256(repr(([tuple(v.co) for v in mesh.vertices],[tuple(f.vertices) for f in mesh.polygons])).encode()).hexdigest()
 if geom!=rec['geometry_sha256']:errors.append(o.name+':geometry')
 if len(mesh.materials)!=1 or mesh.materials[0].name!=row['material'] or any(f.material_index for f in mesh.polygons):errors.append(o.name+':binding')
 layer=mesh.uv_layers['R104_veneer_metres']
 for f in mesh.polygons:
  n=(o.matrix_world.to_3x3().inverted().transposed()@f.normal).normalized()
  for li in f.loop_indices:
   p=o.matrix_world@mesh.vertices[mesh.loops[li].vertex_index].co;phase=rec['phase_m'];wanted=((p.z+phase,p.y) if abs(n.x)>.5 else ((p.z+phase,p.x) if abs(n.y)>.5 else (p.y+phase,p.x))) if rec.get('grain_mapping','vertical')=='vertical' else ((p.y+phase,p.z) if abs(n.x)>.5 else ((p.x+phase,p.z) if abs(n.y)>.5 else (p.y+phase,p.x)))
   if max(abs(x-y) for x,y in zip(wanted,layer.data[li].uv))>1e-5:errors.append(o.name+':metric_uv');break
mat=bpy.data.materials[row['material']];n=mat.node_tree.nodes;bs=n['Principled BSDF'];images=[]
for f in row['files']:
 node=n['R104_'+f['role']];im=node.image;packed=bool(im.packed_file);digest=hashlib.sha256(bytes(im.packed_file.data)).hexdigest() if packed else None
 ok=digest==f['sha256'] and tuple(im.size)==(4096,4096) and im.colorspace_settings.name==('sRGB' if f['role']=='diff' else 'Non-Color') and node.projection=='FLAT' and node.inputs['Vector'].links[0].from_node.uv_map=='R104_veneer_metres'
 images.append({'role':f['role'],'pass':ok,'sha256':digest})
 if not ok:errors.append('Native image/UV contract:'+f['role'])
if bs.inputs['Roughness'].links[0].from_node.name!='R104_rough':errors.append('Roughness not native source')
if bs.inputs['Normal'].links[0].from_node.name!='R104_native_GL_normal':errors.append('Normal not native source')
if n['R104_native_GL_normal'].uv_map!='R104_veneer_metres' or abs(n['R104_native_GL_normal'].inputs['Strength'].default_value-1)>1e-6:errors.append('Normal tangent contract')
if bs.inputs['Base Color'].links[0].from_node.name!='R104_preserved_linear_gain':errors.append('Albedo path')
if max(abs(a-b) for a,b in zip(n['R104_preserved_linear_gain'].inputs[2].default_value[:3],row['linear_basecolor_gain']))>1e-6:errors.append('Wrong authored finish gain')
if len(names)!=17:errors.append('Expected17realpanels')
out.write_text(json.dumps({'source':m['candidate'],'source_sha256':sha(m['candidate']),'panel_count':len(names),'baseline_objects_checked':len(baseline),'images':images,'errors':errors,'pass':not errors,'photorealism_accepted':False,'scope':'17unchanged panel meshes/transforms,exactworldmetreUV,packed4K/PBRdata identity and active roughness/GLnormal,other existing transform/data/material bindings. No roughness calibration,measuredBRDF,full geometry-collision or photographic acceptance.'},indent=2));assert not errors,errors
