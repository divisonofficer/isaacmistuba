"""Source-bound candidate semantics for two physically authored core WCs; no canonical overwrite."""
import bpy,json,copy,hashlib,sys
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from shapely.geometry import Polygon
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from wc_layout_checks import evaluated_geometry,bounds
d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r116_draft.blend';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();source_sha=sha(src);original=(d/'room_mapping.json').read_bytes();mapping=json.loads(original);result=copy.deepcopy(mapping);bpy.ops.wm.open_mainfile(filepath=str(src));architecture=[]
for o in bpy.context.scene.objects:
 if o.type!='MESH' or not(o.name.endswith(('.wall','.exterior')) or o.name.startswith('Core104_')):continue
 lo,hi=bounds(o)
 if hi.x<7 or lo.x>14.5 or hi.y<6 or lo.y>9.6:continue
 ev,me,ps=evaluated_geometry(o);tree=BVHTree.FromPolygons(ps,[tuple(f.vertices) for f in me.polygons]);ev.to_mesh_clear();architecture.append((o.name,tree))
rows=[]
for unit in [101,102]:
 mirror=lambda x:21.5-x if unit==102 else x;cx=mirror(8.45);tests=[('west_partition',(cx,9.0,1.3),(-1 if unit==101 else 1,0,0)),('east_partition',(cx,9.0,1.3),(1 if unit==101 else -1,0,0)),('south_partition',(cx,8.5,1.3),(0,-1,0)),('north_partition',(cx,8.5,1.3),(0,1,0))];hits=[]
 for label,start,direction in tests:
  candidates=[]
  for name,t in architecture:
   loc,n,idx,dist=t.ray_cast(Vector(start),Vector(direction),2)
   if loc is not None:candidates.append((dist,name,loc))
  assert candidates,(unit,label);dist,name,loc=min(candidates,key=lambda v:v[0]);hits.append({'boundary':label,'object':name,'point_m':list(loc),'distance_m':dist})
 xs=sorted([hits[0]['point_m'][0],hits[1]['point_m'][0]]);ys=[hits[2]['point_m'][1],hits[3]['point_m'][1]];assert abs(xs[1]-xs[0]-.8709306)<.005 and abs(ys[1]-ys[0]-1.7709306)<.005,(unit,xs,ys)
 wc=Polygon([(mirror(x),y) for x,y in [(7.9,7.5),(9,7.5),(9,9.5),(7.9,9.5)]]);hallkey=f'{unit}_living_entry';old=Polygon(mapping[hallkey]['polygon_m']);hall=old.difference(wc);assert hall.geom_type=='Polygon' and abs(hall.area+wc.area-old.area)<1e-8;result[hallkey]['polygon_m']=[list(x) for x in list(hall.exterior.coords)[:-1]];key=f'{unit}_core_wc';fixturekeys=[str(o.get('program_key')) for o in bpy.context.scene.objects if o.type=='MESH' and str(o.get('program_key','')).startswith(key)];assert key+'_wc' in fixturekeys;door=next(o for o in bpy.context.scene.objects if o.get('program_key')==key+'_door');result[key]={'room_id':f'authored_core_wc_{unit}','polygon_m':[list(x) for x in list(wc.exterior.coords)[:-1]],'room_type':'wc','source_floor_object':mapping[hallkey]['room_id']+'.floor','geometry_objects':[h['object'] for h in hits],'actual_inner_bbox_xy_m':[xs[0],ys[0],xs[1],ys[1]],'actual_door_object':door.name,'door_mechanism':'hinged_native_leaf','hinge_world_m':list(door['core104_hinge_world_m']),'open_angle_deg':door['core104_open_angle_deg'],'fixture_program_keys':fixturekeys,'annotation_status':'source_bound_candidate_not_canonical'};rows.append({'unit':unit,'actual_wall_boundary_hits':hits,'new_room_key':key,'new_semantic_area_m2':wc.area,'remaining_entry_area_m2':hall.area,'semantic_partition_overlap_m2':hall.intersection(wc).area,'native_room_floor_object_exists':bpy.data.objects.get(f'authored_core_wc_{unit}.floor') is not None,'source_floor_object':result[key]['source_floor_object']})
wcobjects=[o for o in bpy.context.scene.objects if o.type=='MESH' and str(o.get('program_key','')).endswith('_wc')];assert len(wcobjects)==10;assert all(str(o['program_key'])[:-3] in result for o in wcobjects);assert (d/'room_mapping.json').read_bytes()==original and sha(src)==source_sha;(d/'room_mapping_candidate_r116.json').write_text(json.dumps(result,indent=2));(d/'room_annotation_candidate_r116_evidence.json').write_text(json.dumps({'source':str(src),'source_sha256':source_sha,'canonical_mapping_sha256':hashlib.sha256(original).hexdigest(),'rows':rows,'mapped_actual_toilet_count':10,'canonical_overwritten':False,'scope':'Candidate sidecar ties all10 actual WCs to room tags; two new core rooms are measured against real wall boundaries and hinged native doors, replacing prior planning-only pocket-door assumption. Existing floor objects reused explicitly. Canonical plan/importer integration, complete door/casing600mm paths and global circulation remain unaccepted.','accepted':False},indent=2));print('CORE116_CANDIDATE_ROOM_TAGS',len(wcobjects))
