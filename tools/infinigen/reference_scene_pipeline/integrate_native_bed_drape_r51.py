"""Two bedroom2 beds:closed measured mattress and source-fitted native gravity cloth,with separate throw layer."""
import bpy,bmesh,json,hashlib,os
import numpy as np
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r50.blend';out=base/'scene_candidate_r51.blend';pilot=ref/'native_duvet_cloth_pilot02.blend';assert not out.exists();assert pilot.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));state=ref/'native_bed_drape_r51_job.json';job={'pid':os.getpid(),'phase':'integrating','source':str(src)}
def status(phase,**kw):job.update(phase=phase,**kw);state.write_text(json.dumps(job,indent=2));print(phase,kw,flush=True)
def parts(mesh):
 adjacency=[[] for _ in mesh.vertices]
 for e in mesh.edges:a,b=e.vertices;adjacency[a].append(b);adjacency[b].append(a)
 pending=set(range(len(mesh.vertices)));rows=[]
 while pending:
  stack=[pending.pop()];ids=set()
  while stack:
   i=stack.pop();ids.add(i)
   for j in adjacency[i]:
    if j in pending:pending.remove(j);stack.append(j)
  a=np.array([mesh.vertices[i].co for i in ids]);faces=[f for f in mesh.polygons if f.vertices[0] in ids];rows.append({'ids':ids,'lo':a.min(0),'hi':a.max(0),'faces':faces})
 return rows

def attach(name,data,parent,key):
 o=bpy.data.objects.new(name,data);bpy.context.scene.collection.objects.link(o);o.parent=parent;o['reference_scene_owner']='dual_unit_residential_floor_03';o['program_key']=key;o['audit_kind']='fixture';return o

def evaluated(o):
 bpy.context.view_layer.update();ev=o.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=ev.to_mesh();points=[o.matrix_local@v.co for v in mesh.vertices];polys=[list(f.vertices) for f in mesh.polygons];ev.to_mesh_clear();return BVHTree.FromPolygons(points,polys),points

try:
 status('loading_native_cloth')
 with bpy.data.libraries.load(str(pilot),link=False) as (a,b):b.objects=['NativeBlanket_duvet_cloth_pilot']
 proto=b.objects[0];assert proto is not None;bpy.context.scene.collection.objects.link(proto);native=proto.data.copy();assert len(native.vertices)>3000;native.transform(proto.matrix_world);rows=[]
 for unit in [101,102]:
  key=f'{unit}_bedroom2_bed';bed=next(o for o in bpy.data.objects if o.get('program_key')==key);pose=bed.matrix_world.copy();old=next(o for o in bpy.data.objects if o.get('program_key')==key+'_draped_duvet');white=old.data.materials[0];throwmat=old.data.materials[1];bed.data=bed.data.copy();groups=parts(bed.data);mattresses=[p for p in groups if abs(p['lo'][2]-.25)<.002 and abs(p['hi'][2]-.55)<.002 and p['hi'][0]-p['lo'][0]>1.9];assert len(mattresses)==1;m=mattresses[0];expected=np.array([[.13,-.68,.25],[2.13,.68,.55]]);assert np.max(abs(np.array([m['lo'],m['hi']])-expected))<.002
  remove=[p for p in groups if p is m or (all(bed.data.materials[f.material_index].name.startswith('ir_sfb_white') for f in p['faces']) and p['lo'][0]>=.60)];assert len(remove)==3,(key,[(p['lo'].tolist(),p['hi'].tolist()) for p in remove]);ids=set().union(*(p['ids'] for p in remove));bm=bmesh.new();bm.from_mesh(bed.data);bm.verts.ensure_lookup_table();bmesh.ops.delete(bm,geom=[bm.verts[i] for i in ids],context='VERTS');bm.to_mesh(bed.data);bm.free();bed.data.update();bpy.data.objects.remove(old,do_unlink=True)
  bm=bmesh.new();bmesh.ops.create_cube(bm,size=1);bmesh.ops.scale(bm,vec=Vector((2,1.36,.30)),verts=bm.verts);bmesh.ops.bevel(bm,geom=list(bm.edges),offset=.04,segments=5,affect='EDGES');bmesh.ops.translate(bm,vec=Vector((1.13,0,.40)),verts=bm.verts);mesh=bpy.data.meshes.new('R51_closed_mattress');bm.to_mesh(mesh);bm.free();mesh.materials.append(white);mattress=attach('R51_closed_measured_mattress',mesh,bed,key+'_closed_mattress')
  for f in mesh.polygons:f.use_smooth=True
  wn=mattress.modifiers.new('Mattress weighted normals','WEIGHTED_NORMAL');wn.keep_sharp=True
  mesh=native.copy();mesh.materials.clear();mesh.materials.append(white);cloth=attach('R51_native_gravity_duvet',mesh,bed,key+'_draped_duvet');cloth['infinigen_factory']='BlanketFactory';cloth['gravity_drape_frames']=60;solid=cloth.modifiers.new('Actual textile thickness','SOLIDIFY');solid.thickness=.012;solid.offset=0;sub=cloth.modifiers.new('Native cloth interpolation','SUBSURF');sub.levels=1;sub.render_levels=1
  # Separate actual 4mm textile layer follows the settled cover,not a painted material stripe.
  mesh=native.copy();bm=bmesh.new();bm.from_mesh(mesh);bmesh.ops.delete(bm,geom=[f for f in bm.faces if not 1.35<f.calc_center_median().x<1.84],context='FACES');loose=[v for v in bm.verts if not v.link_faces]
  if loose:bmesh.ops.delete(bm,geom=loose,context='VERTS')
  bm.to_mesh(mesh);bm.free();mesh.update()
  for v in mesh.vertices:v.co+=v.normal*.009
  mesh.update();mesh.materials.clear();mesh.materials.append(throwmat);throw=attach('R51_separate_textile_throw',mesh,bed,key+'_physical_throw');solid=throw.modifiers.new('Throw physical thickness','SOLIDIFY');solid.thickness=.004;solid.offset=0;sub=throw.modifiers.new('Throw interpolation','SUBSURF');sub.levels=1;sub.render_levels=1
  mt,mp=evaluated(mattress);ct,cp=evaluated(cloth);tt,tp=evaluated(throw);overlap={'duvet_mattress':len(ct.overlap(mt)),'throw_duvet':len(tt.overlap(ct))};assert not any(overlap.values()),(key,overlap);gap=min(mt.find_nearest(v)[3] for v in cp);assert gap<.02,(key,gap);bm=bmesh.new();bm.from_mesh(mattress.data);boundary=sum(not e.is_manifold for e in bm.edges);bm.free();assert boundary==0;assert bed.matrix_world==pose
  rows.append({'bed':key,'removed_components':len(remove),'removed_vertices':len(ids),'closed_mattress_bounds_m':expected.tolist(),'mattress_nonmanifold_edges':boundary,'surface_overlap_pairs':overlap,'minimum_duvet_mattress_vertex_gap_m':gap,'duvet_thickness_m':.012,'throw_thickness_m':.004,'throw_note':'separate conformed patch from same settled native grid;not independently simulated','unchanged_bed_world_matrix':[list(r) for r in pose]});status('unit_complete',unit=unit)
 bpy.data.objects.remove(proto,do_unlink=True);bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r51.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'pilot':str(pilot),'pilot_sha256':hashlib.sha256(pilot.read_bytes()).hexdigest(),'scope':'two bedroom2 mattress/duvet/throw only;bedroom layout,headboard,pillows,materials andlighting retained','beds':rows,'photorealism_accepted':False,'remaining':'source room front/reverse visual review;bed pillows andcomforter fill/hem unresolved;other four beds still analytic'},indent=2));status('candidate_saved_visual_review_pending',candidate=str(out))
except Exception as e:status('failed',error=str(e));raise
