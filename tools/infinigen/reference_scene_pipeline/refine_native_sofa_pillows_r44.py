"""Replace four rounded-box throw pillows with native pressure-cloth PillowFactory geometry."""
import bpy,bmesh,json,math,hashlib
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r43.blend';out=base/'scene_candidate_r44.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src))
panel_meta=json.loads((ref/'native_pillow_panel_rest90_prototypes.json').read_text());outline_audit=json.loads((ref/'pillow_projected_outline_audit.json').read_text());outline=next(x for x in outline_audit['prototypes'] if x['file']=='native_pillow_panel_rest90_prototypes.blend' and x['object']=='NativePanelRestPillow_0');assert outline['gross_projected_outline_gate_pass'];assert outline['source_sha256']==hashlib.sha256((ref/'native_pillow_panel_rest90_prototypes.blend').read_bytes()).hexdigest()
with bpy.data.libraries.load(str(ref/'native_pillow_panel_rest90_prototypes.blend'),link=False) as (a,b):b.objects=['NativePanelRestPillow_0']
proto=b.objects[0];bpy.context.scene.collection.objects.link(proto);bpy.context.view_layer.update();ev=proto.evaluated_get(bpy.context.evaluated_depsgraph_get());native=bpy.data.meshes.new_from_object(ev);native_tree=BVHTree.FromPolygons([v.co for v in native.vertices],[list(f.vertices) for f in native.polygons]);polysets=[set(f.vertices) for f in native.polygons];coordinate_sets=[{tuple(round(float(x),7) for x in native.vertices[i].co) for i in f.vertices} for f in native.polygons];overlap_pairs=[(i,j) for i,j in native_tree.overlap(native_tree) if j>i and not polysets[i]&polysets[j] and not coordinate_sets[i]&coordinate_sets[j]];assert not overlap_pairs,('evaluated native pillow self-overlap',len(overlap_pairs))
native_width=max(v.co.x for v in native.vertices)-min(v.co.x for v in native.vertices);native_height=max(v.co.y for v in native.vertices)-min(v.co.y for v in native.vertices);scale=min(.46/native_width,.4/native_height);equator=[]
for k in range(129):
 t=k*math.tau/128;origin=Vector((native_width*math.cos(t),native_height*math.sin(t),0));hit,normal,_,_=native_tree.ray_cast(origin,-origin.normalized(),origin.length*2);assert hit is not None;equator.append(hit+normal*.0002)
rows=[]
for unit in [101,102]:
 parent=next(o for o in bpy.data.objects if o.get('program_key')==f'{unit}_living_sectional');parent.data=parent.data.copy();slots=[i for i,m in enumerate(parent.data.materials) if m and m.name.startswith('ir_sec_pillow_')];assert len(slots)==2
 colors=[parent.data.materials[i] for i in slots];bm=bmesh.new();bm.from_mesh(parent.data);remove=[f for f in bm.faces if f.material_index in slots];bmesh.ops.delete(bm,geom=remove,context='FACES');loose=[v for v in bm.verts if not v.link_faces]
 if loose:bmesh.ops.delete(bm,geom=loose,context='VERTS')
 bm.to_mesh(parent.data);bm.free();parent.data.update();pv=[v.co.copy() for v in parent.data.vertices]
 seatpolys=[list(f.vertices) for f in parent.data.polygons if parent.data.materials[f.material_index].name=='ir_sec_cushion' and f.normal.z>.25];backpolys=[list(f.vertices) for f in parent.data.polygons if f.center.x<.30 and f.center.z>.42 and f.normal.x>.1];assert seatpolys and backpolys
 seat=BVHTree.FromPolygons(pv,seatpolys);back=BVHTree.FromPolygons(pv,backpolys)
 for index,yc in enumerate([-.8,.2]):
  R=Matrix.Rotation(-.15 if index==0 else -.19,4,'Y')@Matrix.Rotation(.08 if index==0 else -.07,4,'Z')
  def transform(v):return R@Vector((v.z*scale,v.x*scale,v.y*scale))
  mesh=native.copy()
  for v in mesh.vertices:v.co=transform(v.co)
  mesh.materials.clear();mesh.materials.append(colors[index]);mesh.update();positions=[v.co.copy() for v in mesh.vertices];cx,cz=.42,.8
  for iteration in range(3):
   zs=[]
   for q in positions:
    hit,_,_,_=seat.ray_cast(Vector((q.x+cx,q.y+yc,2)),Vector((0,0,-1)),3)
    if hit is not None:zs.append(hit.z-q.z+.0005)
   assert zs;cz=max(zs);xs=[]
   for q in positions:
    hit,_,_,_=back.ray_cast(Vector((3,q.y+yc,q.z+cz)),Vector((-1,0,0)),3)
    if hit is not None:xs.append(hit.x-q.x+.0005)
   assert xs;cx=max(xs)
  center=Vector((cx,yc,cz));placed=[v+center for v in positions];body=BVHTree.FromPolygons(placed,[list(f.vertices) for f in mesh.polygons]);intersections={'seat':len(body.overlap(seat)),'back':len(body.overlap(back))};assert not any(intersections.values()),('surface intersection',unit,index,intersections)
  minseat=min(seat.find_nearest(v)[3] for v in placed);minback=min(back.find_nearest(v)[3] for v in placed);assert minseat<.003 and minback<.003,(unit,index,minseat,minback)
  obj=bpy.data.objects.new(f'NativeR44_{unit}_pressure_pillow_{index}',mesh);bpy.context.scene.collection.objects.link(obj);obj.parent=parent;obj.location=center;obj['reference_scene_owner']='dual_unit_residential_floor_03';obj['program_key']=f'{unit}_native_sofa_pillow_{index}';obj['audit_kind']='detail';obj['infinigen_factory']='PillowFactory';obj['factory_seed']=842110
  curve=bpy.data.curves.new('Native_pillow_perimeter_seam','CURVE');curve.dimensions='3D';curve.bevel_depth=.00045;curve.bevel_resolution=3;spline=curve.splines.new('POLY');spline.points.add(len(equator)-1)
  for dst,p in zip(spline.points,equator):dst.co=(*transform(p),1)
  curve.materials.append(colors[index]);seam=bpy.data.objects.new('NativeR44_pillow_seam',curve);bpy.context.scene.collection.objects.link(seam);seam.parent=obj;seam['reference_scene_owner']='dual_unit_residential_floor_03';seam['program_key']=f'{unit}_native_pillow_seam_{index}';seam['audit_kind']='detail'
  rows.append({'object':obj.name,'native_factory':'PillowFactory','factory_seed':842110,'uniform_fit':scale,'local_center':list(center),'minimum_vertex_to_seat_distance_m':minseat,'minimum_vertex_to_back_distance_m':minback,'triangle_overlap_pairs':intersections,'perimeter_seam_radius_m':.00045})
bpy.data.objects.remove(proto,do_unlink=True);bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r44.json').write_text(json.dumps({'source':str(src),'candidate':str(out),'source_sha256':sha,'scope':'4 sofa throw pillows only,compared to43single textile material. Native pressure-cloth loft with90percent low-stretch panel correction from verified native UV,actual129point seam and surface-placed supports. Not a new full physics solve.', 'prototype':panel_meta,'projected_silhouette_audit':outline,'gate_note':'Z=0 cross-section was16.38mm and failed;that section is not the visible silhouette when seam warps inZ. Exact evaluated-edge central-plane intersections show actual projected outline recession max6.19mm,under unchanged15mm criterion. Both measurements preserved.', 'evaluated_nonadjacent_self_overlap_pairs':len(overlap_pairs),'pillows':rows,'lighting_materials':'unchanged;existing textile response retained for geometry-only comparison','photorealism_accepted':False,'requires':'same-camera sofa detail,independent image review,whole scene/source regression;bed pillows/cushion bodies remain separate work'},indent=2));print('SAVED',out,flush=True)
