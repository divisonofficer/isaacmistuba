"""Restore measured missing native wall surfaces per plan v3, preserve door opening."""
import bpy,bmesh,json,hashlib,re
from pathlib import Path
from mathutils import Vector
from shapely.geometry import Polygon,box
from shapely.ops import unary_union,triangulate
from shapely import make_valid
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';B=R/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';S=B/'scene_candidate_r92.blend';O=B/'scene_candidate_r93.blend';assert not O.exists();probe=json.loads((D/'private_conference_partition_probe_r92.json').read_text());assert probe['no_scene_modified'];bpy.ops.wm.open_mainfile(filepath=str(S));records=[]
def pieces(g):
 if g.is_empty:return []
 if g.geom_type=='Polygon':return [g]
 return [p for child in getattr(g,'geoms',[]) for p in pieces(child)]
def planar(o,plane):
 out=[]
 for f in o.data.polygons:
  pts=[o.matrix_world@o.data.vertices[i].co for i in f.vertices]
  if max(abs(p.y-plane) for p in pts)>1e-5:continue
  shape=make_valid(Polygon([(p.x,p.z) for p in pts]))
  if shape.area>1e-10:out.append((f.index,shape,f.material_index,(o.matrix_world.to_3x3()@f.normal).normalized()))
 return out
for name,xlo,xhi,expected_y in [('office_0/5.wall',.95,4.,17.8910785),('office_0/9.wall',4.,4.22,17.8910785),('office_0/6.wall',.95,4.22,18.1089215)]:
 o=bpy.data.objects[name];candidates=[]
 for f in o.data.polygons:
  pts=[o.matrix_world@o.data.vertices[i].co for i in f.vertices]
  if max(p.y for p in pts)-min(p.y for p in pts)<1e-5 and abs(pts[0].y-expected_y)<.005:candidates.append((f.area,pts[0].y))
 assert candidates,name;plane=max(candidates)[1];old=planar(o,plane);assert old;cover=unary_union([v[1] for v in old]);target=box(xlo,.1089215,xhi,2.6910785);missing=target.difference(cover);assert missing.area>.01,(name,missing.area);tris=[]
 for p in pieces(missing):tris.extend(t for t in triangulate(p) if p.covers(t) and t.area>1e-12)
 assert abs(sum(t.area for t in tris)-missing.area)<1e-6
 normal=max(old,key=lambda v:v[1].area)[3];mat=max(old,key=lambda v:v[1].area)[2];o.data=o.data.copy();bm=bmesh.new();bm.from_mesh(o.data);inverse=o.matrix_world.inverted();uv=bm.loops.layers.uv.active
 for t in tris:
  coords=[Vector((x,plane,z)) for x,z in list(t.exterior.coords)[:-1]];verts=[bm.verts.new(inverse@v) for v in coords];f=bm.faces.new(verts);f.material_index=mat;f.normal_update()
  if (o.matrix_world.to_3x3()@f.normal).dot(normal)<0:f.normal_flip()
  if uv:
   for loop in f.loops:
    world=o.matrix_world@loop.vert.co;loop[uv].uv=(world.x,world.z)
 bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-6);bm.normal_update();bm.to_mesh(o.data);bm.free();o.data.update();after=unary_union([v[1] for v in planar(o,plane)]);assert target.difference(after).area<1e-5;assert after.difference(cover).difference(target).area<1e-5
 records.append({'object':name,'plane_y':plane,'target_x':[xlo,xhi],'target_z':[.1089215,2.6910785],'native_material_index':mat,'added_missing_area_m2':missing.area,'new_triangles':len(tris),'uncovered_target_area_m2':target.difference(after).area,'unchanged_outside_target':True})
removed=[]
for o in list(bpy.context.scene.objects):
 if re.fullmatch(r'Office02_glazing_(?:(?:mullion|rail)_)?6_0(?:\.\d+)?',o.name):removed.append(o.name);bpy.data.objects.remove(o,do_unlink=True)
# Blender suffix names use literal dots; select any remaining exact family safely.
for o in list(bpy.context.scene.objects):
 base=o.name.split('.')[0]
 if base in ['Office02_glazing_6_0','Office02_glazing_mullion_6_0','Office02_glazing_rail_6_0']:removed.append(o.name);bpy.data.objects.remove(o,do_unlink=True)
assert len(removed)==5,removed
assert bpy.data.objects.get('Office02_glazing_6_1') is not None
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(O));(D/'realism_refinement_r93.json').write_text(json.dumps({'source':str(S),'source_sha256':hashlib.sha256(S.read_bytes()).hexdigest(),'candidate':str(O),'candidate_sha256':hashlib.sha256(O.read_bytes()).hexdigest(),'change':'Plan-v3 privacy correction:fill only missing planar regions on3 existing native wall meshes along conference/private6 boundary,remove the erroneous shared glass/frame6_0. No new box furniture,other door/glass6_1/world/lights/materials/exposure changes.','plan_reference':'floorplan_reference_v3.png','measured_source_probe':'private_conference_partition_probe_r92.json','native_wall_patches':records,'removed_erroneous_glazing_family':removed,'retained_door_interval_x':[4.3,5.3],'retained_public_glazing':'Office02_glazing_6_1','scope':'Build only,not full closed-solid wall/UV/nav or photo certification. Need saved bidirectional privacy rays,door/public-glass preservation checks and controlled diagnostics.','retained_revision':92,'photorealism_accepted':False},indent=2)+'\n');print('OFFICE_PRIVATE_PARTITION_R93_SAVED',flush=True)
