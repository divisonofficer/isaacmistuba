"""Room trial: replace24 faceted shower cylinders by reviewed native-profile toiletries.
Keep shower,glass,shelf andall unrelated parent geometry/materials unchanged.
"""
import bpy,bmesh,json,hashlib
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
root=Path('/jarvis/project/robomituba');base=root/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=root/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r67.blend';out=base/'scene_candidate_r68.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));showers=[o for o in bpy.data.objects if o.type=='MESH' and 'ShowerEnclosureFactory' in o.name];assert len(showers)==8
studio=ref/'native_toiletries_studio68_configured_fit02';scope=json.loads((studio/'scope.json').read_text());names=tuple(n for row in scope['records'] for n in row['prototype_objects'])
with bpy.data.libraries.load(str(studio/'studio.blend'),link=False) as (a,b):b.objects=list(names)
loaded=dict(zip(names,b.objects));assert all(loaded.values())
for o in loaded.values():bpy.context.collection.objects.link(o)
bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();templates=[]
for row in scope['records']:
 objects=[loaded[n] for n in row['prototype_objects']];points=[]
 for o in objects:
  ev=o.evaluated_get(deps);m=ev.to_mesh();points.extend(o.matrix_world@v.co for v in m.vertices);ev.to_mesh_clear()
 lo=Vector([min(v[k] for v in points) for k in range(3)]);hi=Vector([max(v[k] for v in points) for k in range(3)]);templates.append((objects,Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z)),hi.z-lo.z))
def signature(me,exclude):
 return hashlib.sha256(repr(sorted((tuple(sorted(tuple(round(float(c),7) for c in me.vertices[i].co) for i in p.vertices)),me.materials[p.material_index].name,p.use_smooth) for p in me.polygons if not any(i in exclude for i in p.vertices))).encode()).hexdigest()
records=[]
for parent in showers:
 me=parent.data;slots=[next(i for i,m in enumerate(me.materials) if m and m.name==f'ir_shower_bottle_{k}') for k in range(3)];old=[]
 for k,slot in enumerate(slots):
  fs=[f for f in me.polygons if f.material_index==slot];ids={i for f in fs for i in f.vertices};assert len(fs)==14 and len(ids)==24;vs=[me.vertices[i].co for i in ids];lo=Vector([min(v[q] for v in vs) for q in range(3)]);hi=Vector([max(v[q] for v in vs) for q in range(3)]);old.append((ids,lo,hi))
 shelf_faces=[f for f in me.polygons if f.material_index==3];shelf_ids={i for f in shelf_faces for i in f.vertices};assert len(shelf_faces)==6 and len(shelf_ids)==8;shelf_points=[me.vertices[i].co for i in shelf_ids];slo=Vector([min(v[q] for v in shelf_points) for q in range(3)]);shi=Vector([max(v[q] for v in shelf_points) for q in range(3)]);assert abs(shi.z-1.056)<1e-5
 removed=set().union(*(x[0] for x in old));before=signature(me,removed);bm=bmesh.new();bm.from_mesh(me);bm.verts.ensure_lookup_table();bmesh.ops.delete(bm,geom=[bm.verts[i] for i in removed],context='VERTS');bm.to_mesh(me);bm.free();me.update();assert signature(me,set())==before
 for k,(_,lo,hi) in enumerate(old):
  objects,anchor,height=templates[k];scale=(hi.z-lo.z)/height;place=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,shi.z));M=parent.matrix_world@Matrix.Translation(place)@Matrix.Scale(scale,4)@Matrix.Translation(-anchor);new=[]
  for proto in objects:
   matrix=M@proto.matrix_world;o=proto.copy();o.data=proto.data;bpy.context.collection.objects.link(o);o.parent=parent;o.matrix_parent_inverse=Matrix.Identity(4);o.matrix_world=matrix;o.name=f'NativeToiletry68_{parent["program_key"]}_{k}_{proto.name}';o['program_key']=parent['program_key']+f'__detail__toiletry_{k}_'+proto.name;o['audit_kind']='detail';o['toiletry_group']=k;o['toiletry_source_seed']=scope['records'][k]['seed'];new.append(o)
  bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();points=[]
  for o in new:
   ev=o.evaluated_get(deps);m=ev.to_mesh();xform=parent.matrix_world.inverted()@o.matrix_world;points.extend(xform@v.co for v in m.vertices);ev.to_mesh_clear()
  nlo=Vector([min(v[q] for v in points) for q in range(3)]);nhi=Vector([max(v[q] for v in points) for q in range(3)]);gap=nlo.z-shi.z;assert abs(gap)<2e-6;assert nlo.x>=slo.x and nhi.x<=shi.x and nlo.y>=slo.y and nhi.y<=shi.y
  # Actual shelf surface ray at the assembly center,not inferred from a label node.
  tree=BVHTree.FromPolygons([v.co.copy() for v in me.vertices],[tuple(f.vertices) for f in me.polygons if f.material_index==3]);hit,n,index,d=tree.ray_cast(Vector((place.x,place.y,nlo.z+.002)),Vector((0,0,-1)),.1);assert hit is not None and abs(nlo.z-hit.z)<2e-6
  records.append({'parent':parent.name,'group':k,'source_seed':scope['records'][k]['seed'],'parts':[o.name for o in new],'height_m':nhi.z-nlo.z,'uniform_scale':scale,'support_gap_m':gap,'actual_shelf_ray_hit_z':hit.z,'xy_within_shelf':True,'unchanged_nonbottle_parent_signature':before})
for o in loaded.values():bpy.data.objects.remove(o,do_unlink=True)
assert len(records)==24;bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r68.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'prototype_source':str(studio/'studio.blend'),'prototype_sha256':hashlib.sha256((studio/'studio.blend').read_bytes()).hexdigest(),'changes':records,'photorealism_accepted':False,'scope':'24 native-profile body/cap/fitted-label/lid/hinge assemblies. Existing shower/shelf/glass/material/pose unchanged. Bounded support/footprint checks,not full-scene collisions orfluid/hinge simulation.','requires':'saved-source preflights,same-camera bathroom wides andfresh independent review before adopting'},indent=2));print('Saved',out,'assemblies',len(records),flush=True)
