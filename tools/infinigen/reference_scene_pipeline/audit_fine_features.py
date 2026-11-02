"""Targeted physical/mesh gates for the actual Fine refinements, beyond material tags."""
import argparse,bpy,json,hashlib,math
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
p=argparse.ArgumentParser();p.add_argument('--blend',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bpy.ops.wm.open_mainfile(filepath=str(a.blend.resolve()));bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();hardware=[];garments=[];seams=[];errors=[];cache={}
for o in bpy.data.objects:
 key=o.get('program_key','')
 if o.type=='MESH' and key.endswith('_wc'):
  attribute=o.data.attributes.get('hardware');total=good=0
  if attribute and attribute.domain=='FACE':
   for f,val in zip(o.data.polygons,attribute.data):
    if val.value<=.5:continue
    total+=1;m=o.data.materials[f.material_index];bs=next((n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None) if m and m.use_nodes else None
    good+=bool(bs and not bs.inputs['Metallic'].is_linked and bs.inputs['Metallic'].default_value==1)
  hardware.append({'object':o.name,'native_hardware_faces':total,'metal_faces':good,'pass':total>0 and total==good})
  if total and total!=good:errors.append({'object':o.name,'reason':'native_hardware_left_as_ceramic'})
 if o.type=='MESH' and '_native_garment_' in key:
  points=[o.matrix_local@v.co for v in o.data.vertices];bounds=[(min(v[k] for v in points),max(v[k] for v in points)) for k in range(3)];good=bounds[0][0]>=.015 and bounds[0][1]<=.555 and bounds[1][0]>=-1.20 and bounds[1][1]<=.30 and bounds[2][0]>=.04 and bounds[2][1]<=2.26
  garments.append({'object':o.name,'cabinet_local_bounds_m':bounds,'inside_frame':good,'native_factory':o.get('infinigen_factory'),'drape_frames':o.get('gravity_drape_frames')})
  if not good:errors.append({'object':o.name,'reason':'garment_outside_native_wardrobe_frame'})
 if o.type=='CURVE' and any(role in key for role in ('_seat_welt_', '_back_welt_', '_native_pillow_seam_', '_native_pillow_topstitch_', '_native_bed_pillow_seam_')):
  parent=o.parent
  if parent.name not in cache:
   evaluated=parent.evaluated_get(deps);mesh=evaluated.to_mesh();tree=BVHTree.FromPolygons([v.co.copy() for v in mesh.vertices],[list(f.vertices) for f in mesh.polygons]);evaluated.to_mesh_clear();cache[parent.name]=tree
  distances=[cache[parent.name].find_nearest(Vector(pt.co[:3]))[3] for spline in o.data.splines for pt in spline.points];maximum=max(distances);good=maximum<=.0015;seams.append({'object':o.name,'maximum_evaluated_surface_gap_m':maximum,'splines':len(o.data.splines),'evaluated_points':len(distances),'pass':good})
  if not good:errors.append({'object':o.name,'reason':'welt_detached_from_evaluated_cushion','gap_m':maximum})
result={'source':str(a.blend.resolve()),'source_sha256':hashlib.sha256(a.blend.read_bytes()).hexdigest(),'native_hardware':hardware,'native_garments':garments,'evaluated_welt_contacts':seams,'errors':errors,'status':'fine_feature_geometry_pass' if not errors else 'fine_feature_repair_required','photorealism_accepted':False,'scope':'Actual component face material, cabinet containment and evaluated cushion/curve contact. Visual realism and continuous garment collision remain separate.'};a.out.write_text(json.dumps(result,indent=2));print(json.dumps({'hardware_objects':len(hardware),'garments':len(garments),'welt_seams':len(seams),'errors':errors}),flush=True)
