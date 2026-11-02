"""Bounded rigid placement search using actual surface intersections;noauto-adoption."""
import bpy,json,itertools,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';s=r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r94.blend';out=d/'conference_leaf_fit_search_r94.json';assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(s));o=bpy.data.objects['PanelDoorFactory(4643175).spawn_asset(6)'];c=bpy.data.objects['DoorCasingFactory(4643175).spawn_asset(6)'];ev=c.evaluated_get(bpy.context.evaluated_depsgraph_get());m=ev.to_mesh();ct=BVHTree.FromPolygons([c.matrix_world@v.co for v in m.vertices],[list(f.vertices) for f in m.polygons]);ev.to_mesh_clear();faces=[f for f in o.data.polygons if f.material_index==0];ids=sorted({i for f in faces for i in f.vertices});lookup={v:i for i,v in enumerate(ids)};pts=[o.matrix_world@o.data.vertices[i].co for i in ids];polys=[[lookup[i] for i in f.vertices] for f in faces];meta=json.loads((d/'realism_refinement_r94.json').read_text());rec=meta['before']['leaf_bounds'];W=Vector((*rec['width_axis'],0));N=Vector((*rec['normal_axis'],0));center=Vector(meta['fitting']['center_world']);width=meta['fitting']['matched_old_leaf_width_height'][0];floor=.10892152786254883;rows=[];tested=0;clear_count=0
for normal_mm,width_mm,z_mm in itertools.product(range(-60,61,5),range(-30,31,5),range(-20,1,5)):
 delta=N*(normal_mm/1000)+W*(width_mm/1000)+Vector((0,0,z_mm/1000));p=[v+delta for v in pts];tested+=1;tree=BVHTree.FromPolygons(p,polys)
 if tree.overlap(ct):continue
 clear_count+=1;gaps=[]
 for z in [.3,1.3,2.3]:
  for offset in [-.0225,0,.0225]:
   q=center-W*(width/2)+N*offset+delta;q.z=z+delta.z;hit=ct.find_nearest(q);gaps.append(hit[3])
 undercut=min(v.z for v in p)-floor
 if undercut<.004:continue
 rows.append({'delta_world_m':list(delta),'delta_leaf_axes_mm':[normal_mm,width_mm,z_mm],'translation_magnitude_m':delta.length,'hinge_edge_vertex_sample_nearest_m':gaps,'minimum_hinge_sample_gap_m':min(gaps),'maximum_hinge_sample_gap_m':max(gaps),'undercut_m':undercut,'triangle_surface_intersection_pairs':0})
rows.sort(key=lambda x:(x['translation_magnitude_m'],x['maximum_hinge_sample_gap_m']));out.write_text(json.dumps({'source':str(s),'source_sha256':hashlib.sha256(s.read_bytes()).hexdigest(),'tested_poses':tested,'surface_clear_poses':clear_count,'eligible_poses':len(rows),'best_minimum_translation':rows[:20],'scope':'Rigidgridtranslations normal/width/Z,actualleaf-casingsurfaceintersection andhinge-nearest/undercutsamples only. No containment/swept volume/hingeassembly/nav orvisual acceptance. Not aneditedscene.'},indent=2));print('LEAF_FIT_SEARCH_COMPLETE',tested,len(rows),flush=True)
