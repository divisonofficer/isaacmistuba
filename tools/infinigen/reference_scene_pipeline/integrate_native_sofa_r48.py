"""Native whole-sofa assembly in both mirrored units,with measured support and real piping."""
import bpy,bmesh,json,hashlib,os,datetime,math
import numpy as np
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';source=base/'scene_candidate_r47.blend';out=base/'scene_candidate_r48.blend';prototype=ref/'native_sofa_engine_prototype_03.blend';assert not out.exists();sha=hashlib.sha256(source.read_bytes()).hexdigest();state=ref/'native_sofa_assembly_r48_job.json';job={'pid':os.getpid(),'phase':'loading_native_assembly','started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()};state.write_text(json.dumps(job,indent=2));bpy.ops.wm.open_mainfile(filepath=str(source))
def status(phase,**kw):job.update(phase=phase,**kw);state.write_text(json.dumps(job,indent=2));print(phase,kw,flush=True)
def groups(mesh):
 adjacency=[[] for _ in mesh.vertices]
 for e in mesh.edges:a,b=e.vertices;adjacency[a].append(b);adjacency[b].append(a)
 pending=set(range(len(mesh.vertices)));result=[]
 while pending:
  stack=[pending.pop()];ids=[]
  while stack:
   i=stack.pop();ids.append(i)
   for j in adjacency[i]:
    if j in pending:pending.remove(j);stack.append(j)
  points=[mesh.vertices[i].co for i in ids];lo=np.min(np.asarray(points),axis=0);hi=np.max(np.asarray(points),axis=0);result.append({'id':len(result),'ids':set(ids),'lo':lo,'hi':hi,'size':hi-lo})
 return result

def part_tree(mesh,faces):
 ids=sorted({i for f in faces for i in f.vertices});mapping={old:i for i,old in enumerate(ids)};points=[mesh.vertices[i].co.copy() for i in ids];polys=[[mapping[i] for i in f.vertices] for f in faces];return BVHTree.FromPolygons(points,polys),points,polys

def child(name,data,parent,key):
 o=bpy.data.objects.new(name,data);bpy.context.scene.collection.objects.link(o);o.parent=parent;o['reference_scene_owner']='dual_unit_residential_floor_03';o['program_key']=key;o['audit_kind']='detail';return o

def frame_box(parent,key,lo,hi,mat):
 bm=bmesh.new();bmesh.ops.create_cube(bm,size=1);size=Vector(hi)-Vector(lo);center=(Vector(lo)+Vector(hi))/2;bmesh.ops.scale(bm,vec=size,verts=bm.verts);bmesh.ops.bevel(bm,geom=list(bm.edges),offset=min(.025,min(size)*.2),segments=6,affect='EDGES');bmesh.ops.translate(bm,vec=center,verts=bm.verts)
 for f in bm.faces:f.smooth=True
 mesh=bpy.data.meshes.new(key);bm.to_mesh(mesh);bm.free();mesh.materials.append(mat);return child('NativeR48_'+key,mesh,parent,key)

try:
 with bpy.data.libraries.load(str(prototype),link=False) as (a,b):b.objects=['NativeSofaEngine_L_candidate']
 proto=b.objects[0];bpy.context.scene.collection.objects.link(proto);native=proto.data.copy();native.transform(proto.matrix_world);allco=np.asarray([list(v.co) for v in native.vertices]);lo=allco.min(axis=0);hi=allco.max(axis=0);width=hi[1]-lo[1];yscale=min(1,3.2/width)
 for v in native.vertices:v.co=Vector((v.co.x-lo[0],(v.co.y-(lo[1]+hi[1])/2)*yscale,v.co.z-lo[2]))
 native.update();parts=groups(native);feet=[p for p in parts if p['hi'][2]<.15 and p['size'][0]<.3 and p['size'][1]<.3];seatparts=[p for p in parts if p['lo'][2]>.15 and p['size'][2]<.24 and min(p['size'][:2])>.35];backparts=[p for p in parts if p['size'][2]>.4 and p['size'][0]<.45 and .4<p['size'][1]<1.1];assert len(seatparts)>=4 and len(backparts)>=3,(len(seatparts),len(backparts));chaise=max(seatparts,key=lambda p:p['size'][0]);assert chaise['size'][0]>1.3
 assert .38<min(p['hi'][2] for p in seatparts)<.5,[(p['lo'].tolist(),p['hi'].tolist()) for p in seatparts]
 footgroups={}
 for p in feet:footgroups.setdefault(tuple(np.round(np.concatenate([p['lo'],p['hi']]),5)),[]).append(p)
 remove=set();keptfeet=[]
 for pair in footgroups.values():
  keep=max(pair,key=lambda p:len(p['ids']));keptfeet.append(keep)
  for p in pair:
   if p is not keep:remove|=p['ids']
 superseded=[]
 for p in seatparts:
  if p is chaise:continue
  overlap=min(p['hi'][1],chaise['hi'][1])-max(p['lo'][1],chaise['lo'][1])
  if overlap>.95*p['size'][1] and p['hi'][0]<chaise['hi'][0]-.3:superseded.append(p);remove|=p['ids']
 assert len(superseded)==1 and len(keptfeet)==4,(len(superseded),len(keptfeet));superseded_ids={p['id'] for p in superseded};seatids={p['id'] for p in seatparts if p['id'] not in superseded_ids};backids={p['id'] for p in backparts};footids={p['id'] for p in keptfeet};vpart={i:p['id'] for p in parts for i in p['ids']};role=native.attributes.new('native_sofa_role','INT','FACE');component=native.attributes.new('native_sofa_component','INT','FACE')
 for f in native.polygons:
  pid=vpart[f.vertices[0]];code=1 if pid in seatids else 2 if pid in backids else 3 if pid in footids else 0;role.data[f.index].value=code;component.data[f.index].value=pid;f.material_index=2 if code==3 else 1 if code in [1,2] else 0
 # Retain one actual native foot shape for the added chaise supports.
 foot=keptfeet[0];fs=[f for f in native.polygons if f.vertices[0] in foot['ids']];ids=sorted(foot['ids']);mapping={old:i for i,old in enumerate(ids)};fc=(foot['lo']+foot['hi'])/2;legdata=bpy.data.meshes.new('NativeR48_chaise_leg_template');legdata.from_pydata([(native.vertices[i].co.x-fc[0],native.vertices[i].co.y-fc[1],native.vertices[i].co.z) for i in ids],[],[[mapping[i] for i in f.vertices] for f in fs]);legdata.materials.append(bpy.data.materials['ir_sec_feet'])
 for f in legdata.polygons:f.use_smooth=True
 bm=bmesh.new();bm.from_mesh(native);bm.verts.ensure_lookup_table();bmesh.ops.delete(bm,geom=[bm.verts[i] for i in remove],context='VERTS');bm.to_mesh(native);bm.free();native.update();native.materials.clear()
 for name in ['ir_sec_fabric','ir_sec_cushion','ir_sec_feet']:native.materials.append(bpy.data.materials[name])
 # Slots were reset;restore actual role assignments.
 for f in native.polygons:
  code=native.attributes['native_sofa_role'].data[f.index].value;f.material_index=2 if code==3 else 1 if code in [1,2] else 0
 for o in list(bpy.data.objects):
  if '_seat_welt_' in o.get('program_key','') or '_back_welt_' in o.get('program_key',''):bpy.data.objects.remove(o,do_unlink=True)
 records=[];seams=[];props=[]
 for unit in [101,102]:
  parent=next(o for o in bpy.data.objects if o.get('program_key')==f'{unit}_living_sectional');parent.data=native.copy()
  for mod in list(parent.modifiers):parent.modifiers.remove(mod)
  parent['infinigen_factory']='SofaFactory';parent['factory_seed']=851101;mesh=parent.data;roles=mesh.attributes['native_sofa_role'];components=mesh.attributes['native_sofa_component'];seatfaces=[f for f in mesh.polygons if roles.data[f.index].value==1];backfaces=[f for f in mesh.polygons if roles.data[f.index].value==2];seat,_,_=part_tree(mesh,seatfaces);back,_,_=part_tree(mesh,backfaces)
  # The native footrest is a cushion without a front chassis: add an actual upholstered base and two matching floor-contact feet.
  base_lo=[.98,float(chaise['lo'][1]+.015),float(foot['hi'][2]*.9+.003)];base_hi=[float(chaise['hi'][0]-.02),float(chaise['hi'][1]-.015),float(chaise['lo'][2]-.0005)];assert base_hi[0]>base_lo[0] and base_hi[2]>base_lo[2];frame_box(parent,f'{unit}_native_chaise_base',base_lo,base_hi,bpy.data.materials['ir_sec_fabric'])
  for j,y in enumerate([base_lo[1]+.08,base_hi[1]-.08]):
   leg=child('NativeR48_chaise_support_leg',legdata,parent,f'{unit}_native_chaise_foot_{j}');leg.location=(base_hi[0]-.10,y,0);assert abs(min(v.co.z for v in legdata.vertices))<1e-5
  # Real circumferential welt on each actual native seat/back pad.
  for pid in sorted(seatids|backids):
   faces=[f for f in mesh.polygons if components.data[f.index].value==pid];tree,points,polys=part_tree(mesh,faces);arr=np.asarray([list(v) for v in points]);C=arr.mean(axis=0);_,axes=np.linalg.eigh(np.cov((arr-C).T));U,V=axes[:,2],axes[:,1];ru=np.max(np.abs((arr-C)@U));rv=np.max(np.abs((arr-C)@V));traced=[];maximum=0
   for k in range(257):
    angle=k*math.tau/256;radial=Vector(2*ru*math.cos(angle)*U+2*rv*math.sin(angle)*V);origin=Vector(C)+radial;hit,normal,_,_=tree.ray_cast(origin,-radial.normalized(),radial.length*2);assert hit is not None,(unit,pid,k);q=hit+normal*.0003;traced.append(q);maximum=max(maximum,tree.find_nearest(q)[3])
   assert maximum<.0015;kind='seat' if pid in seatids else 'back';curve=bpy.data.curves.new('NativeR48_actual_pad_welt','CURVE');curve.dimensions='3D';curve.bevel_depth=.0012;curve.bevel_resolution=3;spline=curve.splines.new('POLY');spline.points.add(len(traced)-1)
   for dst,q in zip(spline.points,traced):dst.co=(*q,1)
   curve.materials.append(bpy.data.materials['ir_sec_cushion']);seam=child('NativeR48_'+kind+'_welt',curve,parent,f'{unit}_{kind}_welt_native_{pid}');seam['support_object']=parent.name;seams.append({'object':seam.name,'pad_component':pid,'kind':kind,'radius_m':.0012,'maximum_surface_gap_m':maximum})
  for pillow in [o for o in bpy.data.objects if o.get('program_key','').startswith(f'{unit}_native_sofa_pillow_')]:
   # Match the new reclined native back without changing the pillow's pressure loft.
   pillow.data=pillow.data.copy();lean=Matrix.Rotation(-.12,4,'Y');pillow.data.transform(lean)
   for seam in pillow.children:
    if seam.type=='CURVE':seam.data=seam.data.copy();seam.data.transform(lean)
   positions=[v.co.copy() for v in pillow.data.vertices];yc=pillow.location.y;cx,cz=.55,.65
   for iteration in range(4):
    zs=[]
    for q in positions:
     hit,_,_,_=seat.ray_cast(Vector((q.x+cx,q.y+yc,2)),Vector((0,0,-1)),3)
     if hit is not None:zs.append(hit.z-q.z+.0005)
    assert zs;cz=max(zs);xs=[]
    for q in positions:
     hit,_,_,_=back.ray_cast(Vector((3,q.y+yc,q.z+cz)),Vector((-1,0,0)),3)
     if hit is not None:xs.append(hit.x-q.x+.0005)
    assert xs;cx=max(xs)
   center=Vector((cx,yc,cz));placed=[q+center for q in positions];tree=BVHTree.FromPolygons(placed,[list(f.vertices) for f in pillow.data.polygons]);overlap={'seat':len(tree.overlap(seat)),'back':len(tree.overlap(back))};assert not any(overlap.values()),(pillow.name,overlap);gaps={'seat':min(seat.find_nearest(q)[3] for q in placed),'back':min(back.find_nearest(q)[3] for q in placed)};assert max(gaps.values())<.003,(pillow.name,gaps);pillow.location=center;props.append({'object':pillow.name,'new_local_center':list(center),'extra_back_lean_rad':-.12,'minimum_vertex_surface_gaps_m':gaps,'triangle_overlap_pairs':overlap});status('fitting_existing_throw_pillows',unit=unit,pillow=pillow.name)
  dims=[max(v.co[k] for v in mesh.vertices)-min(v.co[k] for v in mesh.vertices) for k in range(3)];assert dims[0]<=2.04 and dims[1]<=3.201 and dims[2]<1.05;records.append({'unit':unit,'body_dimensions_m':dims,'seat_pads':len(seatids),'back_pads':len(backids),'native_feet':len(keptfeet),'extra_chaise_feet':2,'chaise_base_bounds':[base_lo,base_hi]});status('unit_assembly_complete',unit=unit)
 bpy.data.objects.remove(proto,do_unlink=True);bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(source.read_bytes()).hexdigest()==sha;meta={'source':str(source),'candidate':str(out),'source_sha256':sha,'native_prototype':str(prototype),'native_prototype_sha256':hashlib.sha256(prototype.read_bytes()).hexdigest(),'change':'Native whole SofaFactory with separated shaped seat/back pads,reference-square arms;preserve parent room poses andmirroring. Remove duplicate native leg representations andsuperseded under-chaise seat;addphysical front chassis/feet. Refit existing throw pillows andactual pad piping.','materials_lights_exposure':'retained from47;this is a whole-sofa assembly geometry comparison','sofas':records,'native_duplicate_foot_representations_removed':len(feet)-len(keptfeet),'superseded_seat_components_removed':len(superseded),'piping':seams,'throw_pillow_contacts':props,'photorealism_accepted':False,'requires':'same-camera wide/close comparison,new independent review,fullsource39views andphysical/navigation regression'};(ref/'realism_refinement_r48.json').write_text(json.dumps(meta,indent=2));status('candidate_saved_visual_review_pending',candidate=str(out))
except Exception as e:status('failed',error=str(e));raise
