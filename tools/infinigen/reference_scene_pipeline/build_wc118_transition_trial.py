"""Bounded actual ceramic transition smoothing; diagnostic, not a scene promotion."""
import bpy,bmesh,json,math,hashlib
from pathlib import Path
from mathutils import Vector
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';p=d/'wc118_transition_trial';assert not p.exists();p.mkdir();src=d/'wc117_support_clearance_trial/candidate.blend';meta=json.loads((d/'wc117_support_clearance_trial/build.json').read_text());bpy.ops.wm.open_mainfile(filepath=str(src));o=bpy.data.objects['NativeFullTankWC100'];mesh=o.data;old=[v.co.copy() for v in mesh.vertices];cx,cy=json.loads((d/'wc109_trap_inlet.json').read_text())['center_xy_m'];n=meta['isolated_bowl_topology']['faces'];ids={v for f in list(mesh.polygons)[:n] for v in f.vertices};adj={i:set() for i in ids}
for e in mesh.edges:
 a,b=e.vertices
 if a in ids and b in ids:adj[a].add(b);adj[b].add(a)
weights={}
for i in ids:
 v=old[i];rho=math.sqrt(((v.x-cx)/.0633)**2+((v.y-cy)/.0419)**2);w=max(0,1-abs(v.z-.156)/.032)*max(0,1-abs(rho-1)/.65)
 if w>0:weights[i]=w*w*(3-2*w)
for iteration in range(24):
 updates={}
 for i,w in weights.items():
  if not adj[i]:continue
  average=sum((mesh.vertices[j].co for j in adj[i]),Vector())/len(adj[i]);v=mesh.vertices[i].co+(average-mesh.vertices[i].co)*(.28*w);move=v-old[i]
  if move.length>.003:v=old[i]+move.normalized()*.003
  updates[i]=v
 for i,v in updates.items():mesh.vertices[i].co=v
mesh.update();bm=bmesh.new();bm.from_mesh(mesh);bmesh.ops.recalc_face_normals(bm,faces=bm.faces);counts={'boundary':sum(e.is_boundary for e in bm.edges),'nonmanifold':sum(not e.is_manifold for e in bm.edges)};bm.to_mesh(mesh);bm.free();assert counts=={'boundary':0,'nonmanifold':0};distances=[(v.co-old[i]).length for i,v in enumerate(mesh.vertices)];assert max(distances)<=.003001;assert all(distances[i]<1e-8 for i,v in enumerate(old) if v.z>.385);dst=p/'candidate.blend';bpy.ops.wm.save_as_mainfile(filepath=str(dst));(p/'views.json').write_text((d/'wc117_support_clearance_trial/views.json').read_text());(p/'build.json').write_text(json.dumps({'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'candidate':str(dst),'candidate_sha256':hashlib.sha256(dst.read_bytes()).hexdigest(),'method':'24 bounded weighted neighbour-relaxation steps on ceramic transition around z0.156 and measured elliptical inlet; no shader/light changes','weighted_vertex_count':len(weights),'moved_vertex_count':sum(x>1e-8 for x in distances),'maximum_vertex_displacement_m':max(distances),'topology':counts,'upper_native_coordinates_preserved':True,'scope':'Actual local curvature adjustment capped3mm. Native seat/tank and top rim preserved. Reopened bore audit and matched high-resolution RGB required. Does not certify full self-intersection, ceramic thickness or functional plumbing. Diagnostic only, no residential integration.','accepted':False},indent=2));print('WC118_TRANSITION_SAVED',len(weights),max(distances))
