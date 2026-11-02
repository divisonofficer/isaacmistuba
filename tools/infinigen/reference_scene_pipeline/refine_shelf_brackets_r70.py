"""Replace solid support webs by folded steel L brackets mounted against measured wall surfaces."""
import bpy,bmesh,json,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path('/jarvis/project/robomituba');base=r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r69.blend';dst=base/'scene_candidate_r70.blend';assert not dst.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get()
paint=bpy.data.materials.new('R70_powder_coated_bracket');paint.use_nodes=True;bs=paint.node_tree.nodes['Principled BSDF'];bs.inputs['Base Color'].default_value=(.025,.03,.035,1);bs.inputs['Roughness'].default_value=.46
steel=bpy.data.materials.new('R70_bracket_fastener_steel');steel.use_nodes=True;bs=steel.node_tree.nodes['Principled BSDF'];bs.inputs['Base Color'].default_value=(.42,.44,.46,1);bs.inputs['Metallic'].default_value=1;bs.inputs['Roughness'].default_value=.3
walls={}
for side,room in [('west','utility_0/0'),('east','utility_0/1')]:
 wall=bpy.data.objects[room+'.wall'];ev=wall.evaluated_get(deps);me=ev.to_mesh();walls[side]=(wall.name,BVHTree.FromPolygons([wall.matrix_world@v.co for v in me.vertices],[list(f.vertices) for f in me.polygons]));ev.to_mesh_clear()
objects=[o for o in bpy.data.objects if o.get('program_key') in ['west_shelf_bracket','east_shelf_bracket']];assert len(objects)==8;rows=[]
def mesh_object(name,verts,faces,mat,key):
 me=bpy.data.meshes.new(name);me.from_pydata(verts,[],faces);me.update();bm=bmesh.new();bm.from_mesh(me);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(me);bm.free();me.materials.append(mat);o=bpy.data.objects.new(name,me);bpy.context.scene.collection.objects.link(o);o['reference_scene_owner']='commercial_office_floor_02';o['program_key']=key;o['audit_kind']='fixture';return o
for number,o in enumerate(objects):
 side='west' if o.get('program_key').startswith('west') else 'east';inward=-1 if side=='west' else 1;direction=Vector((0,-inward,0));x=o.location.x;shelves=[q for q in bpy.data.objects if q.get('program_key')==side+'_wall_shelf'];shelf=min(shelves,key=lambda q:abs(q.location.z-(o.location.z+.14)));sp=[shelf.matrix_world@Vector(c) for c in shelf.bound_box];underside=min(q.z for q in sp);origin=Vector((x,shelf.location.y,underside-.12));wallname,tree=walls[side];hit,normal,index,distance=tree.ray_cast(origin,direction,.7);assert hit is not None and abs(normal.y)>.95,(o.name,hit,normal);wall_y=hit.y;mount_y=wall_y+inward*.0005;front=(min(q.y for q in sp)+.025) if side=='west' else (max(q.y for q in sp)-.025);length=(front-mount_y)*inward;assert .20<length<.40,(o.name,length);top=underside-.0005;t=.003;h=.22;w=.025;profile=[(0,0),(length,0),(length,-t),(t,-t),(t,-h),(0,-h)];world=[(x+dx,mount_y+inward*u,top+z) for dx in [-w/2,w/2] for u,z in profile];faces=[tuple(reversed(range(6))),tuple(range(6,12))]+[(i,(i+1)%6,(i+1)%6+6,i+6) for i in range(6)];inverse=o.matrix_world.inverted();local=[tuple(inverse@Vector(q)) for q in world];new=mesh_object('R70_folded_L_bracket',local,faces,paint,'temporary');o.data=new.data;bpy.data.objects.remove(new,do_unlink=True)
 for md in o.modifiers:
  if md.type=='BEVEL':md.width=.0005;md.segments=3
 for level,z in enumerate([top-.035,top-.17]):
  # Closed metal screw-head mesh with actual recessed six-sided socket.
  import math
  count=24;verts=[]
  for depth,radius in [(0,.0035),(.0022,.0035),(.0022,.0014),(.0008,.0014)]:
   for k in range(count):
    a=2*math.pi*k/count;rr=radius if radius>.002 else radius/math.cos((a%(math.pi/3))-math.pi/6);verts.append((x+rr*math.cos(a),mount_y+inward*(t+depth),z+rr*math.sin(a)))
  faces=[]
  for ring in range(3):
   for k in range(count):j=(k+1)%count;faces.append((ring*count+k,ring*count+j,(ring+1)*count+j,(ring+1)*count+k))
  faces.append(tuple(reversed(range(count))));faces.append(tuple(3*count+k for k in range(count)));screw=mesh_object(f'R70_{side}_bracket_screw_{number}_{level}',verts,faces,steel,f'{side}_bracket_screw_{number}_{level}');screw['audit_kind']='detail'
 rows.append({'bracket':o.name,'wall':wallname,'wall_ray_hit':list(hit),'wall_gap_m':.0005,'shelf_gap_m':.0005,'steel_strip_thickness_m':t,'horizontal_length_m':length,'screw_count':2})
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(dst));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r70.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(dst),'change':'8 solid web blocks replaced by3mm folded L steel brackets plus16 recessed-socket fasteners; measured wall surfaces set mount positions; shelf/book poses unchanged','brackets':rows,'photorealism_accepted':False,'limits':'Measured static contact gaps, not structural load analysis. Full collision/nav and visual checks still required.'},indent=2));print(dst,flush=True)
