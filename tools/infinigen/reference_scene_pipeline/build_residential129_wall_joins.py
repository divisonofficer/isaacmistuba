"""Remove measured duplicate architectural wall faces, preserve source128 furniture/lighting."""
import bpy,bmesh,json,hashlib,sys
from pathlib import Path
from mathutils import Vector
from shapely.geometry import Polygon,box
from shapely.ops import unary_union
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from compact_wc_contract import mesh_geometry_hash
from physical_scene_geometry import evaluated_surface
D=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';base=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';src=base/'scene_candidate_r128_draft.blend';dst=base/'scene_candidate_r129_draft.blend';assert not dst.exists();assert (D/'compact128_review/independent_coverage_verified.json').exists();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();source_hash=sha(src);bpy.ops.wm.open_mainfile(filepath=str(src));bpy.context.view_layer.update();original={o.name:{'matrix':[list(v) for v in o.matrix_world],'geometry':mesh_geometry_hash(o.data) if o.type=='MESH' else None} for o in bpy.context.scene.objects};changes=[];changed=set();removed=set()
for unit,rid,x in [(101,'living-room_0/0',6.8854653),(102,'living-room_0/1',14.6145347)]:
 native=bpy.data.objects[rid+'.wall'];vs,fs,used=evaluated_surface(native);polys=[]
 for f in fs:
  pts=[vs[i] for i in f]
  if max(abs(p.x-x) for p in pts)<1e-5:
   poly=Polygon([(p.y,p.z) for p in pts])
   if poly.area>1e-8:polys.append(poly)
 footprint=unary_union(polys); meaningful=footprint.intersection(box(7.55,.12,9.3854653,2.68));cut_y=meaningful.bounds[0];assert 8.98<cut_y<9.0,cut_y
 wall=bpy.data.objects[f'Residential127_{unit}_living_media_privacy_return'];old_end=max(v.co.y for v in wall.data.vertices);wall.data=wall.data.copy()
 for v in wall.data.vertices:
  if abs(v.co.y-old_end)<1e-5:v.co.y=cut_y
 wall.data.update();trim=bpy.data.objects[f'Residential127_{unit}_privacy_return_trim'];trim.data=trim.data.copy();oldtrim=max(v.co.y for v in trim.data.vertices)
 for v in trim.data.vertices:
  if abs(v.co.y-oldtrim)<1e-5:v.co.y=cut_y
 trim.data.update();changed.update([wall.name,trim.name]);remaining=footprint.intersection(box(7.55,.12,cut_y,2.68)).area;assert remaining<1e-7,remaining;changes.append({'unit':unit,'kind':'privacy_wall_butt_joint','old_y_end_m':old_end,'new_y_end_m':cut_y,'new_front_overlap_area_m2':remaining,'old_overlap_area_m2':meaningful.area,'native_wall_untouched':True})
 side=bpy.data.objects[f'Core104_{unit}_WC_side_wall'];south=bpy.data.objects[f'Core104_{unit}_WC_south_wall']
 for operand in [side,south]:
  bm=bmesh.new();bm.from_mesh(operand.data);bad=sum(not e.is_manifold for e in bm.edges);volume=bm.calc_volume(signed=False);bm.free();assert bad==0 and volume>.001,(operand.name,len(operand.data.polygons),bad,volume)

 mod=side.modifiers.new('Physical129_union_overlapping_plaster_walls','BOOLEAN');mod.operation='UNION';mod.solver='EXACT';mod.object=south;bpy.context.view_layer.objects.active=side;bpy.ops.object.modifier_apply(modifier=mod.name);side.data.update();bm=bmesh.new();bm.from_mesh(side.data);bad=sum(not e.is_manifold for e in bm.edges);volume=bm.calc_volume(signed=False);bm.free();assert bad==0 and volume>.01,(unit,bad,volume);removed.add(south.name);bpy.data.objects.remove(south,do_unlink=True);changed.add(side.name);changes.append({'unit':unit,'kind':'actual_core_wall_union','object':side.name,'removed_operand':f'Core104_{unit}_WC_south_wall','polygons':len(side.data.polygons),'nonmanifold_edges':bad,'volume_m3':volume,'method':'EXACT boolean union of two existing overlapping closed wall solids, not an opaque cover or material edit.'})
bpy.context.view_layer.update()
for o in bpy.context.scene.objects:
 if o.name in changed:continue
 assert o.name in original and original[o.name]['matrix']==[list(v) for v in o.matrix_world],o.name
 if o.type=='MESH':assert original[o.name]['geometry']==mesh_geometry_hash(o.data),o.name
assert set(original)-{o.name for o in bpy.context.scene.objects}==removed;bpy.ops.wm.save_as_mainfile(filepath=str(dst));assert sha(src)==source_hash;(D/'wall_joins129_build.json').write_text(json.dumps({'source':str(src),'source_sha256':source_hash,'candidate':str(dst),'candidate_sha256':sha(dst),'changes':changes,'changed_objects':sorted(changed),'removed_architecture':sorted(removed),'unrelated_raw_geometry_and_matrices_unchanged':True,'accepted':False,'scope':'Measured coplanar architectural face overlap removed. Furniture/native sizes/finishes,lights/cameras/world retained from unapproved128. Construction/frame/mount details and bedroom2 native double-door/aperture defect remain open. Saved physical and same-camera RGB checks required; no whole-scene acceptance/promotion.'},indent=2));print('WALL_JOINS129_SAVED',changes,flush=True)
