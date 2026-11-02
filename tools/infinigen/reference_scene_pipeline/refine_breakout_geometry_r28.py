"""Geometry-only breakout pass: shaped upholstery, real seam curves and restrained cabinet gaps."""
import bpy,bmesh,json,math,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';source=base/'scene_candidate_r27.blend';out=base/'scene_candidate_r28.blend';assert not out.exists();sha=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source));records=[]
def sp(x,e):return math.copysign(abs(x)**e,x)
def surface(kind,p,t):
 c=sp(math.cos(p),.35);s=sp(math.sin(p),.35);ct=sp(math.cos(t),.35);st=sp(math.sin(t),.35)
 if kind=='seat':
  x=.23*c*ct;y=.23*c*st;z=.44+.05*s
  if z>.44:z+=.012*max(0,1-(x/.23)**2)*max(0,1-(y/.23)**2)
  return (x,y,z)
 x=-.21+.045*c*ct;y=.22*c*st;z=.70+.21*s;x+=.025*(y/.22)**2-.09*(z-.70);return (x,y,z)
def mark(o,parent,key):o.parent=parent;o['reference_scene_owner']='commercial_office_floor_02';o['program_key']=key;o['audit_kind']='detail'
def welt(parent,kind,material):
 points=[]
 for k in range(129):
  t=k*math.tau/128
  if kind=='seat':p=surface(kind,.40,t)
  else:
   y=.22*sp(math.cos(t),.35);z=.70+.21*sp(math.sin(t),.35);p=(-.21+.025*(y/.22)**2-.09*(z-.70),y,z)
  points.append(p)
 curve=bpy.data.curves.new('Breakout_sewn_welt','CURVE');curve.dimensions='3D';curve.bevel_depth=.0007;curve.bevel_resolution=3;spl=curve.splines.new('POLY');spl.points.add(len(points)-1)
 for dst,co in zip(spl.points,points):dst.co=(*co,1)
 curve.materials.append(material);o=bpy.data.objects.new('BreakoutR28_'+kind+'_welt',curve);bpy.context.scene.collection.objects.link(o);mark(o,parent,parent['program_key']+'_'+kind+'_welt')
for o in list(bpy.data.objects):
 if not o.get('program_key','').startswith('breakout_chair') or o.type!='MESH':continue
 fabidx=next(i for i,m in enumerate(o.data.materials) if m and ('fabric' in m.name or m.get('reference_pbr_kind')=='textile'));fab=o.data.materials[fabidx];bm=bmesh.new();bm.from_mesh(o.data);verts=set(v for f in bm.faces if f.material_index==fabidx for v in f.verts);bmesh.ops.delete(bm,geom=list(verts),context='VERTS');bm.to_mesh(o.data);bm.free()
 for kind in ['seat','back']:
  vertices=[];faces=[];N=64;M=32
  for j in range(1,M):
   p=-math.pi/2+math.pi*j/M
   for k in range(N):vertices.append(surface(kind,p,math.tau*k/N))
  bottom=len(vertices);vertices.append(surface(kind,-math.pi/2,0));top=len(vertices);vertices.append(surface(kind,math.pi/2,0))
  for j in range(M-2):
   for k in range(N):faces.append((j*N+k,j*N+(k+1)%N,(j+1)*N+(k+1)%N,(j+1)*N+k))
  for k in range(N):faces.extend([(bottom,(k+1)%N,k),(top,(M-2)*N+k,(M-2)*N+(k+1)%N)])
  mesh=bpy.data.meshes.new('Breakout_shaped_'+kind);mesh.from_pydata(vertices,[],faces);mesh.materials.append(fab)
  for f in mesh.polygons:f.use_smooth=True
  child=bpy.data.objects.new('BreakoutR28_shaped_'+kind,mesh);bpy.context.scene.collection.objects.link(child);mark(child,o,o['program_key']+'_'+kind+'_upholstery');welt(o,kind,fab)
 records.append({'chair':o['program_key'],'retained':'native legs,world pose,fabric shader','new':'compound curved back,domed seat,0.7mm welt','silhouette_requires':'same-camera comparison and chair closeup'})
# Existing door reveals were15mm. Reduce to3mm; preserve centers and cabinet wall layout.
for o in bpy.data.objects:
 key=o.get('program_key','')
 if key in ['coffee_cabinet_front','coffee_upper_front']:
  o.dimensions.y=3.5/6-.003
  for mod in o.modifiers:
   if mod.type=='BEVEL':mod.width=.0015;mod.segments=3
  records.append({'cabinet':o.name,'door_reveal_m':.003,'edge_radius_m':.0015})
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(source.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r28.json').write_text(json.dumps({'source':str(source),'candidate':str(out),'source_sha256':sha,'scope':'geometry only;lighting and shaders retained','changes':records,'photorealism_accepted':False},indent=2));print('SAVED',out,flush=True)
