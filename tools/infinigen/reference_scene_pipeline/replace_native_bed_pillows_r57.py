"""Native pressure-cloth bed pillow assembly,with separate filled bodies and verified support."""
import bpy,bmesh,json,hashlib,math,os
import numpy as np
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r52.blend';out=base/'scene_candidate_r57.blend';protos=ref/'native_pillow_panel_rest65_prototypes.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));state=ref/'native_bed_pillows_r57_job.json';job={'pid':os.getpid(),'phase':'loading_native_pressure_shapes'}
def status(phase,**kw):job.update(phase=phase,**kw);state.write_text(json.dumps(job,indent=2));print(phase,kw,flush=True)
def tree(mesh):return BVHTree.FromPolygons([v.co.copy() for v in mesh.vertices],[list(f.vertices) for f in mesh.polygons])
def self_overlap(mesh):
 t=tree(mesh);sets=[set(f.vertices) for f in mesh.polygons];coords=[{tuple(round(float(x),7) for x in mesh.vertices[i].co) for i in f.vertices} for f in mesh.polygons];return [(i,j) for i,j in t.overlap(t) if j>i and not sets[i]&sets[j] and not coords[i]&coords[j]]
def combined(objects,positive_x=False):
 points=[];faces=[];deps=bpy.context.evaluated_depsgraph_get()
 for obj in objects:
  ev=obj.evaluated_get(deps);mesh=ev.to_mesh();off=len(points);points.extend([(obj.matrix_local@v.co if obj.parent else v.co.copy()) for v in mesh.vertices]);faces.extend([[i+off for i in f.vertices] for f in mesh.polygons if not positive_x or f.normal.x>.05]);ev.to_mesh_clear()
 return BVHTree.FromPolygons(points,faces),points

from pressure_contour_refinement import make_shape as pressure_shape
from pillow_shape_refinement import make_shape as prior_shape
def make_shape(native,width,height,depth,angle,roll):
 return pressure_shape(native,width,height,depth,angle,roll) if width>.5 else prior_shape(native,width,height,depth,angle,roll)

def fit(obj,support,support_points,back,back_points,yc):
 points=[v.co.copy() for v in obj.data.vertices];dx,dz=.4,.8
 def back_x(z):
  values=[]
  for q in points:
   hit,_,_,_=back.ray_cast(Vector((3,q.y+yc,q.z+z)),Vector((-1,0,0)),4)
   if hit is not None:values.append(hit.x-q.x+.0005)
  assert values;return max(values)
 for i in range(6):
  values=[]
  for q in points:
   hit,_,_,_=support.ray_cast(Vector((q.x+dx,q.y+yc,3)),Vector((0,0,-1)),4)
   if hit is not None:values.append(hit.z-q.z+.0005)
  assert values;dz=max(values);dx=back_x(dz)
 clearance=0
 for i in range(21):
  center=Vector((dx,yc,dz));placed=[q+center for q in points];body=BVHTree.FromPolygons(placed,[list(f.vertices) for f in obj.data.polygons]);overlap={'support':len(body.overlap(support)),'back':len(body.overlap(back))}
  if not any(overlap.values()):break
  if overlap['support']:dz+=.001;clearance+=.001;dx=back_x(dz)
  if overlap['back']:dx+=.001
 assert not any(overlap.values()),(obj.name,overlap)
 gaps={'support':min(min(support.find_nearest(q)[3] for q in placed),min(body.find_nearest(q)[3] for q in support_points)),'back':min(min(back.find_nearest(q)[3] for q in placed),min(body.find_nearest(q)[3] for q in back_points))};assert max(gaps.values())<.003,(obj.name,gaps);obj.location=center;return {'center_local_m':list(center),'surface_overlap_pairs':overlap,'minimum_bidirectional_vertex_surface_gap_m':gaps,'extra_clearance_m':clearance}

def piping(obj,unit,kind,index):
 mesh=obj.data;t=tree(mesh);a=np.array([list(v.co) for v in mesh.vertices]);C=a.mean(0);_,axes=np.linalg.eigh(np.cov((a-C).T));U,V=axes[:,2],axes[:,1];ru=max(abs((a-C)@U));rv=max(abs((a-C)@V));curve=bpy.data.curves.new('R53_actual_pillow_piping','CURVE');curve.dimensions='3D';curve.bevel_depth=.0006;curve.bevel_resolution=3;spline=curve.splines.new('POLY');spline.points.add(256);gap=0
 for k,p in enumerate(spline.points):
  angle=k*math.tau/256;radial=Vector(2*ru*math.cos(angle)*U+2*rv*math.sin(angle)*V);hit,n,_,_=t.ray_cast(Vector(C)+radial,-radial.normalized(),radial.length*2);assert hit is not None;q=hit+n*.0002;p.co=(*q,1);gap=max(gap,t.find_nearest(q)[3])
 curve.materials.append(mesh.materials[0]);seam=bpy.data.objects.new('R53_native_bed_pillow_piping',curve);bpy.context.scene.collection.objects.link(seam);seam.parent=obj;seam['program_key']=f'{unit}_native_bed_pillow_seam_{kind}_{index}';seam['reference_scene_owner']='dual_unit_residential_floor_03';seam['audit_kind']='detail';return gap
try:
 status('loading_native_pressure_shapes')
 with bpy.data.libraries.load(str(protos),link=False) as (a,b):b.objects=['NativePanelRestPillow_0','NativePanelRestPillow_1']
 native={};imported=[]
 for i,obj in enumerate(b.objects):
  bpy.context.scene.collection.objects.link(obj);imported.append(obj);bpy.context.view_layer.update();mesh=bpy.data.meshes.new_from_object(obj.evaluated_get(bpy.context.evaluated_depsgraph_get()));assert not self_overlap(mesh),('native prototype self-overlap',i);native[i]=mesh
 # Keep the teal prototype exactly as in55; only white uses the reviewed65percent contour.
 with bpy.data.libraries.load(str(ref/'native_pillow_panel_rest90_prototypes.blend'),link=False) as (aa,bb):bb.objects=['NativePanelRestPillow_0']
 oldteal=bb.objects[0];bpy.context.scene.collection.objects.link(oldteal);imported.append(oldteal);bpy.context.view_layer.update();native[0]=bpy.data.meshes.new_from_object(oldteal.evaluated_get(bpy.context.evaluated_depsgraph_get()))
 records=[]
 for unit in [101,102]:
  bed=next(o for o in bpy.data.objects if o.get('program_key')==f'{unit}_bedroom2_bed');bed.data=bed.data.copy();white=next(m for m in bed.data.materials if m.name.startswith('ir_sfb_white'));teal=next(m for m in bed.data.materials if m.name.startswith('ir_sfb_petrol'));slots={i for i,m in enumerate(bed.data.materials) if m.name.startswith(('ir_sfb_white','ir_sfb_greige','ir_sfb_petrol'))};bm=bmesh.new();bm.from_mesh(bed.data);ids={v for f in bm.faces if f.material_index in slots for v in f.verts};removed=len(ids);assert removed>500;bmesh.ops.delete(bm,geom=list(ids),context='VERTS');bm.to_mesh(bed.data);bm.free();bed.data.update();bpy.context.view_layer.update();supports=[next(o for o in bpy.data.objects if o.get('program_key')==f'{unit}_bedroom2_bed'+suffix) for suffix in ['_closed_mattress','_draped_duvet']];support,sp=combined(supports);head,hp=combined([bed],True);whites=[];all_bodies=[]
  for kind in ['white','teal']:
   if kind=='teal':back,bp=combined(whites)
   else:back,bp=head,hp
   for index,sign in enumerate([-1,1]):
    width,height,depth=(.62,.42,.113) if kind=='white' else (.38,.28,.055);mesh,compression=make_shape(native[1 if kind=='white' else 0],width,height,depth,-.24 if kind=='white' else -.30,sign*.035);mesh.materials.clear();mesh.materials.append(white if kind=='white' else teal);obj=bpy.data.objects.new(f'R53_{unit}_native_{kind}_bed_pillow_{index}',mesh);bpy.context.scene.collection.objects.link(obj);obj.parent=bed;obj['program_key']=f'{unit}_native_bed_pillow_{kind}_{index}';obj['reference_scene_owner']='dual_unit_residential_floor_03';obj['audit_kind']='detail';obj['infinigen_factory']='PillowFactory';obj['bed_pillow_kind']=kind;obj['bed_pillow_unit']=unit;obj['factory_seed']=842111 if kind=='white' else 842110;contact=fit(obj,support,sp,back,bp,sign*.32);seamgap=piping(obj,unit,kind,index);all_bodies.append(obj)
    if kind=='white':whites.append(obj)
    records.append({'object':obj.name,'unit':unit,'kind':kind,'native_shape_target_width_height_halfdepth_m':[width,height,depth],'loft_profile':'White: native65percent-rest contour and pressure depth,axis/scale only;teal:unchanged90percent-rest prototype and55 kernel','static_lower_edge_compression_max_m':compression,'actual_smooth_polygons':sum(f.use_smooth for f in mesh.polygons),'contact':contact,'piping_radius_m':.0006,'piping_maximum_surface_gap_m':seamgap});status('pillow_complete',unit=unit,kind=kind,index=index)
  pairwise=[]
  for i,a in enumerate(all_bodies):
   ta,_=combined([a])
   for b in all_bodies[i+1:]:
    tb,_=combined([b]);n=len(ta.overlap(tb));assert n==0,(a.name,b.name,n);pairwise.append({'a':a.name,'b':b.name,'triangle_overlaps':n})
  status('bed_assembly_verified',unit=unit,removed_legacy_vertices=removed,pairwise=pairwise)
 for obj in imported:bpy.data.objects.remove(obj,do_unlink=True)
 bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r57.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'shape_kernel_sha256':hashlib.sha256(Path(__file__).with_name('pressure_contour_refinement.py').read_bytes()).hexdigest(),'native_prototype_file':str(protos),'native_prototype_sha256':hashlib.sha256(protos.read_bytes()).hexdigest(),'scope':'White pillows use independently reviewed65percent-rest contour;teal body geometry stays on55 recipe butsupport pose refitted. Headboard,mattress,cloth,materials,lighting androom unchanged.','pillows':records,'photorealism_accepted':False,'limitations':'Source52 assembly rebuilt withnative pressure shape andstatic rim/corner/loft/lower-edge refinement. Failed53/54 are comparisons only;not a full new contact physics solve. Sofa pillows andother4beds unchanged.','requires':'actual front/reverse renders,independent review,saved evaluated assembly/support audit andwhole source regression'},indent=2));status('candidate_saved_visual_review_pending',candidate=str(out))
except Exception as e:status('failed',error=str(e));raise
