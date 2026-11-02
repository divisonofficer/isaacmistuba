"""Replace only measured native fridge box and two tiny handles; retain all other kitchen faces."""
import bpy,bmesh,json,hashlib,math
from pathlib import Path
from mathutils import Matrix,Vector
r=Path('/jarvis/project/robomituba');base=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r65.blend';out=base/'scene_candidate_r66.blend';assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
def signature(me,exclude):
 return hashlib.sha256(repr(sorted((tuple(sorted(tuple(round(c,7) for c in me.vertices[i].co) for i in p.vertices)),me.materials[p.material_index].name,p.use_smooth) for p in me.polygons if not any(i in exclude for i in p.vertices))).encode()).hexdigest()
def finish(o,parent,mat,bevel=0):
 o.parent=parent;o.matrix_parent_inverse=Matrix.Identity(4);o.matrix_basis=Matrix.Identity(4);o.data.materials.append(mat);o['audit_kind']='detail';o['program_key']=parent['program_key']+'__detail__'+o.name
 if bevel:
  m=o.modifiers.new('Manufactured edge radius','BEVEL');m.width=bevel;m.segments=3;m.limit_method='ANGLE';m=o.modifiers.new('Planar face normals','WEIGHTED_NORMAL');m.keep_sharp=True
 return o
cube_faces=[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
def box(name,lo,hi,parent,mat,radius):
 vs=[(lo[0],lo[1],lo[2]),(hi[0],lo[1],lo[2]),(hi[0],hi[1],lo[2]),(lo[0],hi[1],lo[2]),(lo[0],lo[1],hi[2]),(hi[0],lo[1],hi[2]),(hi[0],hi[1],hi[2]),(lo[0],hi[1],hi[2])];me=bpy.data.meshes.new(name);me.from_pydata(vs,[],cube_faces);me.update();o=bpy.data.objects.new(name,me);bpy.context.collection.objects.link(o);return finish(o,parent,mat,radius)
def rod(name,start,end,radius,parent,mat):
 a=Vector(start);b=Vector(end);axis=(b-a).normalized();u=axis.cross(Vector((0,1,0))).normalized();v=axis.cross(u);N=48;vs=[tuple(c+radius*(u*math.cos(k*math.tau/N)+v*math.sin(k*math.tau/N))) for c in [a,b] for k in range(N)];fs=[tuple(reversed(range(N))),tuple(range(N,2*N))]+[(k,(k+1)%N,(k+1)%N+N,k+N) for k in range(N)];me=bpy.data.meshes.new(name);me.from_pydata(vs,[],fs);me.update();o=bpy.data.objects.new(name,me);bpy.context.collection.objects.link(o);finish(o,parent,mat)
 for p in me.polygons:p.use_smooth=len(p.vertices)==4
 return o
for parent in [o for o in bpy.data.objects if o.type=='MESH' and 'HomeKitchenRunFactory' in o.name]:
 me=parent.data;fs=[p for p in me.polygons if p.material_index==7];ids={i for p in fs for i in p.vertices};assert len(fs)==6 and len(ids)==8;vs=[me.vertices[i].co for i in ids];lo=[min(v[k] for v in vs) for k in range(3)];hi=[max(v[k] for v in vs) for k in range(3)];assert all(abs(a-b)<1e-4 for a,b in zip(lo+hi,[0,-1.25,0,.7,-.53,1.85]));cy=(lo[1]+hi[1])/2
 handles={v.index for v in me.vertices if .6939<v.co.x<.7061 and abs(v.co.y-cy)<.0061 and ((.9999<v.co.z<1.6001) or (.3999<v.co.z<.7001))};assert len(handles)==16, len(handles);removed=ids|handles;before=signature(me,removed);metal=me.materials[7];assert metal and 'steel' in metal.name.lower()
 bm=bmesh.new();bm.from_mesh(me);bm.verts.ensure_lookup_table();bmesh.ops.delete(bm,geom=[bm.verts[i] for i in removed],context='VERTS');bm.to_mesh(me);bm.free();me.update();assert signature(me,set())==before
 trim=bpy.data.materials.get('Fridge66_graphite_gasket')
 if not trim:
  trim=bpy.data.materials.new('Fridge66_graphite_gasket');trim.use_nodes=True;bs=trim.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(.035,.038,.04,1);bs.inputs['Roughness'].default_value=.54
 key=parent['program_key'];parts=[];parts.append(box('Fridge66_body_'+key,(0,lo[1],0),(.65,hi[1],1.85),parent,metal,.004));parts.append(box('Fridge66_gasket_'+key,(.65,lo[1]+.003,.05),(.664,hi[1]-.003,1.84),parent,trim,.001))
 for label,z0,z1 in [('freezer',.055,.696),('fridge',.704,1.838)]:parts.append(box('Fridge66_'+label+'_'+key,(.664,lo[1]+.004,z0),(.7,hi[1]-.004,z1),parent,metal,.003))
 for label,z0,z1 in [('lower',.42,.62),('upper',.88,1.38)]:
  for z in [z0+.018,z1-.018]:parts.append(rod('Fridge66_mount_'+label+'_'+str(z)+'_'+key,(.699,cy,z),(.738,cy,z),.009,parent,metal))
  parts.append(rod('Fridge66_pull_'+label+'_'+key,(.738,cy,z0),(.738,cy,z1),.008,parent,metal))
 rows.append({'kitchen':parent.name,'removed_fridge_box_vertices':8,'removed_handle_vertices':16,'unchanged_other_faces_signature':before,'parts':[o.name for o in parts],'door_split_gap_m':.008,'door_side_clearance_m':.004,'door_bevel_m':.003,'handle_front_projection_m':.046,'scope':'Closed appliance exterior only;not openable/interior or whole-scene collision certification.'})
assert len(rows)==2;bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));(ref/'realism_refinement_r66.json').write_text(json.dumps({'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'candidate':str(out),'changes':rows,'photorealism_accepted':False,'requires':'Saved four gates andsamecamera kitchen A/B with65;fresh independent review before adoption'},indent=2));print('Saved',out,flush=True)
