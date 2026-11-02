"""Manufactured kitchen details and luminaire/light-source parity; no diagnostic softbox."""
import bpy,math,json,hashlib
from pathlib import Path
from mathutils import Vector
from material_detail import material,noise,bump,range_value
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r28.blend';out=base/'scene_candidate_r29.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));changes=[]
def mat(name,color,rough,metal=0):return material(name,color,rough,metal)[0]
chrome,n,l,bs,tc,geo=material('BreakoutR29_polished_chrome',(.67,.69,.72),.105,1);tex=noise(n,l,geo.outputs['Position'],1100);l.new(range_value(n,l,tex,.095,.115),bs.inputs['Roughness']);l.new(bump(n,l,tex,.0000008,.08),bs.inputs['Normal']);chrome['reference_pbr_kind']='bare_metal'
coat=mat('BreakoutR29_luminaire_powder_coat',(.64,.65,.64),.39);dark=mat('BreakoutR29_aerator_recess',(.015,.016,.018),.65);white=mat('BreakoutR29_socket_moulding',(.72,.72,.69),.33);diffuser=mat('BreakoutR29_opal_diffuser',(.78,.79,.78),.26)
bs=next(n for n in diffuser.node_tree.nodes if n.type=='BSDF_PRINCIPLED');bs.inputs['Emission Color'].default_value=(.94,.96,1,1);bs.inputs['Emission Strength'].default_value=.65
scene='commercial_office_floor_02'
def mark(o,key):o['reference_scene_owner']=scene;o['program_key']=key;o['audit_kind']='detail';return o
def box(key,loc,size,m,r=.0008):
 # Direct datablock construction avoids operator overhead on a scene with hundreds of objects.
 p=[(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)];faces=[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)];mesh=bpy.data.meshes.new(key);mesh.from_pydata([tuple(v[i]*size[i]/2 for i in range(3)) for v in p],[],faces);mesh.materials.append(m);o=bpy.data.objects.new('BreakoutR29_'+key,mesh);bpy.context.scene.collection.objects.link(o);o.location=loc
 if r:bev=o.modifiers.new('Manufactured_radius','BEVEL');bev.width=r;bev.segments=3;o.modifiers.new('Planar_normal','WEIGHTED_NORMAL')
 return mark(o,key)
def rod(key,start,end,r,m):
 start=Vector(start);end=Vector(end);axis=end-start;z=axis.normalized();x=z.cross(Vector((1,0,0)) if abs(z.x)<.8 else Vector((0,1,0))).normalized();y=z.cross(x);N=48;verts=[tuple(center+r*(math.cos(k*math.tau/N)*x+math.sin(k*math.tau/N)*y)) for center in (start,end) for k in range(N)];faces=[(k,(k+1)%N,N+(k+1)%N,N+k) for k in range(N)]+[tuple(reversed(range(N))),tuple(range(N,2*N))];mesh=bpy.data.meshes.new(key);mesh.from_pydata(verts,[],faces);mesh.materials.append(m)
 for f in mesh.polygons:f.use_smooth=len(f.vertices)==4
 o=bpy.data.objects.new('BreakoutR29_'+key,mesh);bpy.context.scene.collection.objects.link(o);return mark(o,key)
def curve(key,points,r,m):
 data=bpy.data.curves.new(key,'CURVE');data.dimensions='3D';data.bevel_depth=r;data.bevel_resolution=5;data.resolution_u=20;spl=data.splines.new('BEZIER');spl.bezier_points.add(len(points)-1)
 for p,co in zip(spl.bezier_points,points):p.co=co;p.handle_left_type='AUTO';p.handle_right_type='AUTO'
 data.materials.append(m);o=bpy.data.objects.new('BreakoutR29_'+key,data);bpy.context.scene.collection.objects.link(o);return mark(o,key)
floor=bpy.data.objects['kitchen_0/0.floor'];fz=max((floor.matrix_world@Vector(c)).z for c in floor.bound_box);counter=fz+.9175
for o in list(bpy.data.objects):
 if o.get('program_key','') in ['tap_stem','tap_spout']:bpy.data.objects.remove(o,do_unlink=True)
rod('tap_mount',(14.53,4.65,counter),(14.53,4.65,counter+.012),.026,chrome)
curve('tap_gooseneck',[(14.53,4.65,counter+.012),(14.53,4.65,counter+.18),(14.49,4.65,counter+.28),(14.36,4.65,counter+.285),(14.27,4.65,counter+.23),(14.27,4.65,counter+.16)],.0115,chrome)
rod('tap_aerator',(14.27,4.65,counter+.155),(14.27,4.65,counter+.17),.013,chrome);rod('tap_aerator_insert',(14.27,4.65,counter+.154),(14.27,4.65,counter+.155),.009,dark)
rod('tap_mixer_joint',(14.53,4.65,counter+.065),(14.53,4.69,counter+.065),.018,chrome);rod('tap_mixer_lever',(14.53,4.69,counter+.065),(14.53,4.69,counter+.135),.0038,chrome)
for o in list(bpy.data.objects):
 if o.get('program_key','')!='coffee_pull':continue
 loc=o.location.copy();bpy.data.objects.remove(o,do_unlink=True);x=loc.x-.023;y=loc.y;z=loc.z
 for sign in [-1,1]:rod('coffee_pull_mount',(loc.x+.010,y+sign*.042,z),(x,y+sign*.042,z),.0045,chrome)
 rod('coffee_pull',(x,y-.048,z),(x,y+.048,z),.0045,chrome)
# Two functional power outlets on the actual existing splash surface; no room re-layout.
for y in (5.05,6.50):
 box('backsplash_outlet_plate',(14.558,y,1.36),(.008,.105,.075),white,.003)
 for dy in [-.024,.024]:
  for dz in [-.009,.009]:box('outlet_contact_recess',(14.553,y+dy,1.36+dz),(.002,.003,.010),dark,.0004)
# Replace exposed glowing blocks by folded housing + recessed diffuser; match actual area source aperture.
fixtures=[o for o in list(bpy.data.objects) if o.type=='MESH' and 'linear_fixture' in o.name and o.location.x>10 and o.location.y<7]
for old in fixtures:
 c=old.location.copy();size=old.dimensions.copy();bpy.data.objects.remove(old,do_unlink=True);W,L,H=size;t=.002
 box('luminaire_top',(c.x,c.y,c.z+H/2-t/2),(W,L,t),coat)
 for side in [-1,1]:box('luminaire_long_flange',(c.x+side*(W/2-t/2),c.y,c.z),(t,L,H),coat)
 for side in [-1,1]:box('luminaire_end_cap',(c.x,c.y+side*(L/2-t/2),c.z),(W,t,H),coat)
 box('luminaire_recessed_diffuser',(c.x,c.y,c.z-H/2+.006),(W-.012,L-.025,.003),diffuser,.001)
 closest=min((o for o in bpy.data.objects if o.type=='LIGHT' and o.name.startswith('office02_area')),key=lambda o:(Vector((o.location.x,o.location.y))-Vector((c.x,c.y))).length)
 assert (Vector(closest.location[:2])-Vector(c[:2])).length<.1
 closest.data.shape='RECTANGLE';closest.data.size=W-.012;closest.data.size_y=L-.025;closest.location.z=c.z-H/2+.003
 changes.append({'fixture_xy':list(c[:2]),'emitter_size_m':[closest.data.size,closest.data.size_y],'watts_unchanged':closest.data.energy,'housing':'folded shell + recessed diffuser'})
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r29.json').write_text(json.dumps({'source':str(src),'candidate':str(out),'source_sha256':sha,'changes':['smooth chrome gooseneck,real mixer lever and aerator','actual open pull grips with supported standoffs','backsplash electrical plates','folded ceiling fixture housing and aperture-matched lights']+changes,'scope':'no diagnostic side light; no exposure/world change; fixture emission aperture corrected','photorealism_accepted':False},indent=2));print('SAVED',out,flush=True)
