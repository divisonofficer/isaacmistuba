"""Actual core approach prism versus saved evaluated physical wall/door/fixture meshes."""
import bpy,json,hashlib,sys
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from shapely.geometry import LineString,Point
from shapely.ops import triangulate
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from wc_layout_checks import evaluated_geometry,bounds
from physical_scene_geometry import render_mesh_candidates,evaluated_surface
d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r121_draft.blend';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();source_sha=sha(src);bpy.ops.wm.open_mainfile(filepath=str(src));fz=bounds(bpy.data.objects['hallway_0/1.floor'])[1].z;low=fz+.02;high=low+1.75;rows=[];physical_objects,inventory=render_mesh_candidates();(d/'core121_render_mesh_inventory.json').write_text(json.dumps({'source':str(src),'source_sha256':source_sha,'records':inventory,'scope':'All scene mesh objects classified by enabled render-layer collection paths and object hide_render; viewport-only hiding is NOT an exclusion. Camera-hidden surfaces remain conservatively physical. Render-time instances/displacement/opacity are not certified.'},indent=2))
def geometry(o):
 ev,me,ps=evaluated_geometry(o);fs=[tuple(f.vertices) for f in me.polygons];ev.to_mesh_clear();return ps,fs
floors=[]
for o in bpy.context.scene.objects:
 if o.type=='MESH' and o.name.endswith('.floor'):
  lo,hi=bounds(o)
  if hi.z>.5:continue
  ps,fs=geometry(o);floors.append((o.name,BVHTree.FromPolygons(ps,fs)))
for unit in [101,102]:
 points=[(9.4,6.75),(7.45,6.75),(7.45,8.25),(8.45,8.25),(8.45,8.365)]
 if unit==102:points=[(21.5-x,y) for x,y in points]
 line=LineString(points);shape=line.buffer(.3,resolution=48);boundary=list(shape.exterior.coords)[:-1];verts=[];faces=[];lookup={}
 def ix(x,y,z):
  key=(round(x,10),round(y,10),z)
  if key not in lookup:lookup[key]=len(verts);verts.append(Vector((x,y,z)))
  return lookup[key]
 for t in triangulate(shape):
  if not shape.covers(t):continue
  xy=list(t.exterior.coords)[:-1];faces.append(tuple(ix(x,y,low) for x,y in xy));faces.append(tuple(reversed([ix(x,y,high) for x,y in xy])))
 for (x,y),(xx,yy) in zip(boundary,boundary[1:]+boundary[:1]):faces.append((ix(x,y,low),ix(xx,yy,low),ix(xx,yy,high),ix(x,y,high)))
 path_tree=BVHTree.FromPolygons(verts,faces);tested=[];collisions=[];x0,y0,x1,y1=shape.bounds
 for o in physical_objects:
  key=str(o.get('program_key',''))
  lo,hi=bounds(o)
  if hi.x<x0 or lo.x>x1 or hi.y<y0 or lo.y>y1 or hi.z<low or lo.z>high:continue
  ps,fs,used=evaluated_surface(o);tree=BVHTree.FromPolygons(ps,fs,all_triangles=True);overlap=path_tree.overlap(tree);inside=[i for i in used if low+1e-5<ps[i].z<high-1e-5 and shape.contains(Point(ps[i].x,ps[i].y))];row={'object':o.name,'key':key,'surface_crossings':len(overlap),'vertices_inside_route_prism':len(inside)};tested.append(row)
  if overlap or inside:
   row['intersection_face_examples']=[{'path_face': [list(verts[i]) for i in faces[a]], 'obstacle_face': [list(ps[i]) for i in fs[b]]} for a,b in overlap[:3]];row['object_visibility']={'visible_get':o.visible_get(),'hide_render':o.hide_render,'visible_camera':o.visible_camera};row['materials']=[m.name for m in o.data.materials if m];collisions.append(row)
 samples=[];steps=int(line.length/.05)+1
 for i in range(steps+1):
  p=line.interpolate(i/steps,normalized=True);hits=[]
  for name,t in floors:
   loc,n,idx,dist=t.ray_cast(Vector((p.x,p.y,fz+.05)),Vector((0,0,-1)),.3)
   if loc is not None:hits.append((dist,name,loc.z))
  samples.append({'xy':[p.x,p.y],'floor_hit':min(hits)[1:] if hits else None})
 rows.append({'unit':unit,'route_centres_xy_m':points,'route_width_m':.6,'prism_z_bounds_m':[low,high],'physical_scope':'ALL meshes in enabled render collection paths, object hide_render false, evaluated bbox broadphase then actual Blender loop triangles. Camera-hidden surfaces conservatively included; viewport hiding ignored. Unfaced joint points excluded. See full inclusion/exclusion inventory.','tested_objects':tested,'collisions':collisions,'centreline_floor_samples':samples,'centreline_floor_samples_supported':all(x['floor_hit'] for x in samples),'route_clear_in_tested_scope':not collisions and all(x['floor_hit'] for x in samples)})
assert sha(src)==source_sha;out={'source':str(src),'source_sha256':source_sha,'rows':rows,'both_core_routes_clear_in_tested_scope':all(x['route_clear_in_tested_scope'] for x in rows),'render_mesh_inventory':'core121_render_mesh_inventory.json','scope':'Two proposed600mm routes swept vertically from floor+20mm to+1.77m. Actual evaluated surface crossings and enclosed mesh vertices, plus floor support on centerline every<=50mm. Does not certify floor across entire600mm width, doorway motion during passage, all10 bathrooms, room importer tags, accessibility standards or complete navigation.','whole_navigation_accepted':False,'accepted':False};(d/'core121_all_render_mesh_route_audit.json').write_text(json.dumps(out,indent=2));print('CORE121_ALL_RENDER_MESH_ROUTE',out['both_core_routes_clear_in_tested_scope']);print([(x['unit'],x['collisions']) for x in rows])
