"""Verify required rooms, furnishing roles and curated-view aliases on actual scene snapshots."""
import argparse,hashlib,json,sys,collections
from pathlib import Path
import bpy,bmesh
from mathutils import Vector
p=argparse.ArgumentParser();p.add_argument('--blend',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--views',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]);bpy.ops.wm.open_mainfile(filepath=str(a.blend.resolve()));contract=json.loads((a.reference/'scene_contract.json').read_text());mapping=json.loads((a.reference/'room_mapping.json').read_text());office=contract['scene_id']=='commercial_office_floor_02';errors=[];rooms=[];counts=collections.Counter()
for key,row in mapping.items():
 name=row['room_id']+'.floor';o=bpy.data.objects.get(name);good=bool(o and o.type=='MESH' and len(o.data.polygons)>0 and not o.hide_render);rooms.append({'space':key,'floor':name,'present_mesh':good});counts[row['room_id'].split('_',1)[0]]+=1
 if not good:errors.append({'space':key,'reason':'missing_actual_floor_mesh'})
if len(rooms)!=contract['required_room_count']:errors.append({'reason':'wrong_room_count','actual':len(rooms)})
for kind,count in contract['required_semantic_counts'].items():
 if counts[kind]!=count:errors.append({'reason':'wrong_semantic_count','kind':kind,'actual':counts[kind],'expected':count})
owned={}
for o in bpy.data.objects:
 if ((o.type=='MESH' and len(o.data.polygons)>0) or (o.type=='CURVE' and o.data.bevel_depth>0 and any(len(s.points)+len(s.bezier_points)>1 for s in o.data.splines))) and o.get('reference_scene_owner')==contract['scene_id'] and not o.hide_render:owned.setdefault(o.get('program_key',''),[]).append(o.name)
if office:
 required=[f'private_{i}_{role}' for i in range(1,7) for role in ('desk','chair')]+[x+'_table' for x in ('conference_a','meeting_b','meeting_c')]+['reception_desk','coffee_end_panel','coffee_back_panel','coffee_bottom_panel','coffee_plinth','coffee_cabinet_front','coffee_worktop','sink_bottom','tap_stem','coffee_fridge','coffee_machine','breakout_table','support_west_storage','support_east_storage']
else:
 required=[]
 for unit in (101,102):
  required += [f'{unit}_{x}' for x in ('master_bed','bedroom2_bed','bedroom3_bed','living_sectional','living_coffee_table','living_media','kitchen_run','dining_table','dressing','balcony_table')]
  required += [f'{unit}_{room}_{role}' for room in ('ensuite','bathroom1','bathroom2','laundry_wc') for role in ('wc','vanity','shower')]
 required+=['lift_door','stair_lower_tread','stair_upper_tread','stair_half_landing']
def role_check(key):
 direct=owned.get(key,[])
 if direct:return {'role':key,'objects':direct,'pass':True,'representation':'direct_role'}
 if office and key=='sink_bottom':
  names=owned.get('sink_formed_bowl',[])
  if names:
   bowl=bpy.data.objects[names[0]];mesh=bowl.data;zs=[v.co.z for v in mesh.vertices];lo,hi=min(zs),max(zs);floor_area=sum(f.area for f in mesh.polygons if f.normal.z>.999 and f.center.z<(lo+hi)/2);bm=bmesh.new();bm.from_mesh(mesh);closed=bool(bm.edges) and all(e.is_manifold for e in bm.edges);bm.free();good=closed and hi-lo>.1 and floor_area>.01
   return {'role':key,'objects':names,'pass':good,'representation':'formed_bowl_includes_planar_inner_floor','geometry_evidence':{'closed_manifold':closed,'height_m':hi-lo,'lower_positiveZ_flat_face_area_m2':floor_area}}
 if office and key=='tap_stem':
  parts=['tap_mount','tap_gooseneck','tap_mixer_joint','tap_mixer_lever','tap_aerator'];missing=[part for part in parts if not owned.get(part)];names=[name for part in parts for name in owned.get(part,[])]
  if not missing:
   mount=bpy.data.objects[owned['tap_mount'][0]];tube=bpy.data.objects[owned['tap_gooseneck'][0]];points=[mount.matrix_world@v.co for v in mount.data.vertices];tip=Vector((sum(v.x for v in points)/len(points),sum(v.y for v in points)/len(points),max(v.z for v in points)));spline=tube.data.splines[0];start=tube.matrix_world@(spline.bezier_points[0].co if len(spline.bezier_points) else Vector(spline.points[0].co[:3]));gap=(tip-start).length;good=tube.type=='CURVE' and tube.data.bevel_depth>0 and gap<.005
   return {'role':key,'objects':names,'pass':good,'representation':'supported_curved_mixer_assembly','geometry_evidence':{'mount_to_tube_start_gap_m':gap,'tube_radius_m':tube.data.bevel_depth},'required_parts':parts}
  return {'role':key,'objects':names,'pass':False,'representation':'incomplete_curved_mixer_assembly','missing_parts':missing}
 return {'role':key,'objects':[],'pass':False,'representation':'missing'}
roles=[role_check(key) for key in required]
for row in roles:
 if not row['pass']:errors.append({'reason':'missing_furnishing_role','role':row['role']})
views=json.loads(a.views.read_text());names={v['name'] for v in views};aliases={} if office else {'shared_corridor':'shared_corridor_context','elevator':'elevator_context','101_kitchen':'101_kitchen_dining','102_kitchen':'102_kitchen_dining','102_bedroom2':'102_bedroom2_reverse'}
coverage=[]
for key in contract['required_views']:
 actual=key if key in names else aliases.get(key);good=actual in names;coverage.append({'required_view':key,'actual_view':actual,'present':good})
 if not good:errors.append({'reason':'missing_required_view','view':key})
doc={'source':str(a.blend.resolve()),'source_sha256':hashlib.sha256(a.blend.read_bytes()).hexdigest(),'status':'pass_required_spaces_roles_views' if not errors else 'needs_required_space_correction','room_count':len(rooms),'semantic_counts':dict(counts),'rooms':rooms,'required_roles':roles,'required_view_coverage':coverage,'actual_view_count':len(names),'errors':errors,'limitations':['Presence and scene-role tags do not certify furniture dimensions, triangle collisions or reference similarity; those use separate audits and direct visual review.','Replacement camera aliases preserve rejected original camera JSON and require visual acceptance independently.']};a.out.write_text(json.dumps(doc,indent=2));print(json.dumps({'status':doc['status'],'rooms':len(rooms),'roles':len(roles),'errors':errors}),flush=True)
