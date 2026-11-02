"""One screened native high-poly tree in101living; independent source87 branch."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';b=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';s=b/'scene_candidate_r87.blend';out=b/'scene_candidate_r89.blend';assert not out.exists();studio=d/'real_indoor_tree_candidates/review_studio.blend';scope=json.loads((d/'real_indoor_tree_candidates/review_scope.json').read_text());e=next(x for x in scope['assets'] if x['id']=='HSSD_95d1e189e93694bb8eee73a64b0d84a8be5a5057');assert (d/'real_indoor_tree_candidates/blind_visual_review.json').exists();bpy.ops.wm.open_mainfile(filepath=str(s));meta=json.loads((d/'realism_refinement_r87.json').read_text())
with bpy.data.libraries.load(str(studio),link=False) as (src,dst):dst.objects=list(e['objects'])
objects=dst.objects;assert all(objects)
for o in objects:bpy.context.scene.collection.objects.link(o);o.hide_render=False;o.hide_set(False);o.parent=None
bpy.context.view_layer.update();points=[o.matrix_world@v.co for o in objects for v in o.data.vertices];lo=Vector([min(p[k] for p in points) for k in range(3)]);hi=Vector([max(p[k] for p in points) for k in range(3)]);target=Vector((2.65,9.0,0));floor=bpy.data.objects['living-room_0/0.floor'];dg=bpy.context.evaluated_depsgraph_get();ev=floor.evaluated_get(dg);me=ev.to_mesh();tree=BVHTree.FromPolygons([floor.matrix_world@v.co for v in me.vertices],[list(p.vertices) for p in me.polygons]);ev.to_mesh_clear();hit=tree.ray_cast(Vector((target.x,target.y,1)),Vector((0,0,-1)),2)[0];assert hit is not None;target.z=hit.z;delta=target-Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z));nfaces=sum(len(o.data.polygons) for o in objects)
for o in objects:o.location+=delta
bpy.ops.object.select_all(action='DESELECT')
for o in objects:o.select_set(True)
bpy.context.view_layer.objects.active=objects[0];bpy.ops.object.join();plant=bpy.context.object;assert len(plant.data.polygons)==nfaces==97348;plant.name='Residential03_r89_native_ficus_101_living';plant['program_key']='101_living_real_ficus';plant['reference_scene_owner']='dual_unit_residential_floor_03';plant['audit_kind']='furniture';plant['original_asset_id']=e['id'];plant['native_geometry_no_shape_modification']=True;bpy.context.view_layer.update();pts=[plant.matrix_world@v.co for v in plant.data.vertices];pmin=Vector([min(p[k] for p in pts) for k in range(3)]);pmax=Vector([max(p[k] for p in pts) for k in range(3)]);assert pmin.x>.1 and pmax.x<6.9 and pmin.y>6.1 and pmax.y<9.45;assert abs(pmin.z-target.z)<1e-5;assert pmax.z<2.65
# Check actual triangle intersections with nearby furniture;floor_covering is independently reported if present.
planttree=BVHTree.FromPolygons(pts,[list(f.vertices) for f in plant.data.polygons]);collisions=[];checked=[]
for o in bpy.context.scene.objects:
 if o==plant or o.type!='MESH' or o.get('audit_kind') not in ['furniture','floor_covering']:continue
 key=o.get('program_key','')
 if not key.startswith('101_'):continue
 bbox=[o.matrix_world@Vector(v) for v in o.bound_box];omin=Vector([min(p[k] for p in bbox) for k in range(3)]);omax=Vector([max(p[k] for p in bbox) for k in range(3)])
 if not all(pmax[k]>=omin[k] and omax[k]>=pmin[k] for k in range(3)):continue
 ev=o.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=ev.to_mesh();other=BVHTree.FromPolygons([o.matrix_world@v.co for v in mesh.vertices],[list(f.vertices) for f in mesh.polygons]);pairs=len(planttree.overlap(other));ev.to_mesh_clear();checked.append({'object':o.name,'program_key':key,'triangle_surface_overlap_pairs':pairs})
 if pairs:collisions.append(key)
assert not collisions,collisions
bpy.ops.wm.save_as_mainfile(filepath=str(out));meta.update(source=str(s),source_sha256=hashlib.sha256(s.read_bytes()).hexdigest(),candidate=str(out),candidate_sha256=hashlib.sha256(out.read_bytes()).hexdigest(),retained_revision=87,change='One screened native97348-face ficus+basket in101living. Independent branch from87;doesnotinclude88bedding palette. No source geometry/light/world changes. One room trial only.',plant={'object':plant.name,'program_key':plant['program_key'],'asset_id':e['id'],'source_studio':str(studio),'source_sha256':hashlib.sha256(studio.read_bytes()).hexdigest(),'native_faces':nfaces,'material_profile_contract':e['material_profile_contract'],'bounds':[list(pmin),list(pmax)],'floor_z':target.z,'nearby_surface_intersection_checks':checked,'scope':'Joined original meshes,rigid translation only;native geometry/UV/material graph retained. Triangle intersection is not volume containment or nav-clearance proof.'},photorealism_accepted=False,requires='Saved floor/room/nearby geometry andmaterial checks;actual101living+reverse comparison beforeadoption. Shiny faceted leafdetail remainsknownlimitation.');(d/'realism_refinement_r89.json').write_text(json.dumps(meta,indent=2));print('REAL_LIVING_FICUS_R89_SAVED',flush=True)
