"""Replace six integrated plant stand-ins with shared native specimens and hollow liners."""
import bpy,bmesh,json,math,hashlib
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';b=r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';src=b/'scene_candidate_r112_draft.blend';dst=b/'scene_candidate_r113_draft.blend';assert not dst.exists();p=d/'botanical114_products';review=json.loads((d/'botanical114_studio_cpu/visual_review.json').read_text());assert review['assets']['spiderplant_002']['room_trial_eligible'];row=next(x for x in json.loads((p/'scope.json').read_text())['assets'] if x['id']=='spiderplant_002');bpy.ops.wm.open_mainfile(filepath=str(src));pods=[o for o in bpy.context.scene.objects if o.type=='MESH' and str(o.get('program_key','')).startswith('pod_') and '_chair' not in str(o.get('program_key','')) and any(m and m.name.startswith('ir_bench_stem') for m in o.data.materials)];assert len(pods)==6
with bpy.data.libraries.load(str(p/'review_studio.blend'),link=False) as (s,z):z.objects=row['objects']
protos=z.objects
for o in protos:bpy.context.scene.collection.objects.link(o)
bpy.context.view_layer.update();ps=[o.matrix_world@v.co for o in protos for v in o.data.vertices];low=min(v.z for v in ps);root=Vector((0,0,min(v.z for v in ps if math.hypot(v.x,v.y)<.04)));offset=Vector((-root.x,-root.y,-root.z));native=[]
for o in protos:
 me=o.data.copy();me.transform(Matrix.Translation(offset)@o.matrix_world);native.append(me)
soil=bpy.data.materials.new('Office113_actual_planting_soil');soil.use_nodes=True;bs=soil.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(.038,.021,.008,1);bs.inputs['Roughness'].default_value=.91

def meshobj(name,verts,faces,mat):
 me=bpy.data.meshes.new(name);me.from_pydata(verts,[],faces);bm=bmesh.new();bm.from_mesh(me);bmesh.ops.recalc_face_normals(bm,faces=bm.faces);assert all(e.is_manifold for e in bm.edges);bm.to_mesh(me);bm.free();o=bpy.data.objects.new(name,me);bpy.context.scene.collection.objects.link(o);me.materials.append(mat);o['program_key']=name;o['reference_scene_owner']='commercial_office_floor_02';return o

def loop(xh,yh,radius,z):
 out=[]
 for cx,cy,start in [(xh-radius,yh-radius,0),(-xh+radius,yh-radius,90),(-xh+radius,-yh+radius,180),(xh-radius,-yh+radius,270)]:
  for i in range(8):a=math.radians(start+i*90/8);out.append((cx+radius*math.cos(a),cy+radius*math.sin(a),z))
 return out

def tree(o):return BVHTree.FromPolygons([o.matrix_world@v.co for v in o.data.vertices],[tuple(f.vertices) for f in o.data.polygons])
rows=[]
for pi,pod in enumerate(sorted(pods,key=lambda o:o['program_key'])):
 key=pod['program_key'];indices={i for i,m in enumerate(pod.data.materials) if m and (m.name.startswith(('ir_bench_trough','ir_bench_stem','ir_off_leaf_')))};troughindex=next(i for i,m in enumerate(pod.data.materials) if m and m.name.startswith('ir_bench_trough'));liner_mat=pod.data.materials[troughindex];ids={j for f in pod.data.polygons if f.material_index==troughindex for j in f.vertices};points=[pod.matrix_world@pod.data.vertices[i].co for i in ids];lo=Vector([min(v[k] for v in points) for k in range(3)]);hi=Vector([max(v[k] for v in points) for k in range(3)]);center=(lo+hi)/2;xh=(hi.x-lo.x)/2;yh=(hi.y-lo.y)/2
 pod.data=pod.data.copy();bm=bmesh.new();bm.from_mesh(pod.data);remove=[f for f in bm.faces if f.material_index in indices];removed=len(remove);bmesh.ops.delete(bm,geom=remove,context='FACES');loose=[v for v in bm.verts if not v.link_faces]
 if loose:bmesh.ops.delete(bm,geom=loose,context='VERTS')
 bm.to_mesh(pod.data);bm.free();pod.data.update();dt=tree(pod)
 rings=[loop(xh,yh,.025,lo.z),loop(xh,yh,.025,hi.z),loop(xh-.008,yh-.008,.017,hi.z),loop(xh-.008,yh-.008,.017,lo.z+.008)];N=len(rings[0]);vv=[(x+center.x,y+center.y,z) for ring in rings for x,y,z in ring];ff=[]
 for a,bb in [(0,1),(1,2),(2,3)]:
  for i in range(N):ff.append((a*N+i,a*N+(i+1)%N,bb*N+(i+1)%N,bb*N+i))
 ff +=[tuple(reversed(range(N))),tuple(3*N+i for i in range(N))];liner=meshobj('Office113_hollow_liner_'+key,vv,ff,liner_mat);be=liner.modifiers.new('1mm powdercoat arris','BEVEL');be.width=.001;be.segments=3;bpy.context.view_layer.objects.active=liner;bpy.ops.object.modifier_apply(modifier=be.name)
 soilz=hi.z-.012;sv=[(center.x-xh+.009,center.y-yh+.009,soilz),(center.x+xh-.009,center.y-yh+.009,soilz),(center.x+xh-.009,center.y+yh-.009,soilz),(center.x-xh+.009,center.y+yh-.009,soilz)];sv +=[(x,y,soilz-.025) for x,y,z in sv];sf=[(0,1,2,3),(7,6,5,4)]+[(i,(i+1)%4,(i+1)%4+4,i+4) for i in range(4)];earth=meshobj('Office113_soil_volume_'+key,sv,sf,soil);plantrows=[]
 for j,dx in enumerate([-.75,0,.75]):
  yaw=math.radians((pi*61+j*117)%360);objs=[]
  for k,me in enumerate(native):
   o=bpy.data.objects.new(f'Office113_shared_spider_{key}_{j}_{k}',me);bpy.context.scene.collection.objects.link(o);o['shared_botanical_asset']='spiderplant_002';o['program_key']=f'{key}_plant_{j}';objs.append(o)
  chosen=None
  for scale in [.85,.75,.65]:
   pose=Matrix.Translation(Vector((center.x+dx,center.y,soilz-.0005)))@Matrix.Rotation(yaw,4,'Z')@Matrix.Scale(scale,4)
   for o in objs:o.matrix_world=pose
   bpy.context.view_layer.update();pairs=[pair for o in objs for pair in tree(o).overlap(dt)];collisions=len(pairs)
   if pi==0 and j==0:
    counts={}
    for _,face in pairs:
     m=pod.data.materials[pod.data.polygons[face].material_index].name;counts[m]=counts.get(m,0)+1
    diagnostic={'root_estimate':list(root),'native_bounds':[list(min(v[k] for v in ps) for k in range(3)),list(max(v[k] for v in ps) for k in range(3))],'scale':scale,'collisions':counts,'plant_world_bounds':[[min((o.matrix_world@v.co)[k] for o in objs for v in o.data.vertices) for k in range(3)],[max((o.matrix_world@v.co)[k] for o in objs for v in o.data.vertices) for k in range(3)]]};(d/('planters113_centered_fit_'+str(scale)+'.json')).write_text(json.dumps(diagnostic,indent=2))
   if collisions==0:chosen=scale;break
  assert chosen is not None,(key,j,'all plant sizes intersect desk/monitor');plantrows.append({'objects':[o.name for o in objs],'uniform_growth_scale':chosen,'root_location_m':[center.x+dx,center.y,soilz-.0005],'desk_device_raw_surface_intersections':collisions})
 rows.append({'pod':key,'removed_old_plant_liner_faces':removed,'liner':liner.name,'soil':earth.name,'rim_height_m':hi.z,'soil_height_m':soilz,'liner_wall_thickness_m':.008,'plants':plantrows})
for o in protos:bpy.data.objects.remove(o,do_unlink=True)
bpy.ops.wm.save_as_mainfile(filepath=str(dst));(d/'planters113_build.json').write_text(json.dumps({'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'candidate':str(dst),'candidate_sha256':hashlib.sha256(dst.read_bytes()).hexdigest(),'native_library_source':row['source'],'root_anchor_method':'XY canonical axis; lowest mesh vertex within40mm central radius. Approximate basal anchor, not lowest drooping leaf tip.','native_library_sha256':row['source_sha256'],'pods':rows,'accepted':False,'scope':'Six hollow8mm liners and actual soil volumes;18 shared Infinigen spider specimens at explicit uniform growth scales. Existing desk structure/devices unchanged; old plant/solid liner material faces removed. Raw desk/device surface overlap checks only. Soil surface texture, leaf-leaf interference, whole navigation and visual acceptance outstanding.'},indent=2));print('OFFICE113_SHARED_BOTANICAL_PLANTERS_SAVED')
