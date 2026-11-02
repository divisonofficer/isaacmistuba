"""Pack current candidates and build complete, explicitly curated review views."""
import argparse,hashlib,json,math
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector
from shapely.geometry import MultiPoint,Point
from shapely.ops import unary_union
from tile_geometry import projected_floor
ROOT=Path(__file__).resolve().parents[3];p=argparse.ArgumentParser();p.add_argument('--scene',choices=['office','residential'],required=True);a=p.parse_args();office=a.scene=='office';scene='commercial_office_floor_02' if office else 'dual_unit_residential_floor_03';seed=48712502 if office else 48712503;revision=17 if office else 18;base=ROOT/'out/infinigen_v2'/f'kr_{scene}_{seed}'/'full';ref=ROOT/'data/venue_refs/floor_plans_v3'/scene;source=base/f'scene_candidate_r{revision}.blend';out=base/f'scene_review_r{revision}_packed.blend';assert not out.exists();digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();before=digest(source);bpy.ops.wm.open_mainfile(filepath=str(source));old=json.loads((base/('review_views_r5.json' if office else 'review_views_r16.json')).read_text())
excluded={} if office else {'shared_corridor':'Blocked original view replaced by shared_corridor_context','elevator':'Uninformative close original replaced by elevator_context','102_bedroom2':'Door-occluded original replaced by 102_bedroom2_reverse','101_dressing':'Close original replaced by dressing_context','102_dressing':'Close original replaced by dressing_context'}
views=[v for v in old if v['name'] not in excluded]
if not office:
 for v in views:
  if v['name'] in ('101_kitchen','102_kitchen'):v['name']=v['name']+'_dining'
def bounds(o):return [o.matrix_world@Vector(c) for c in o.bound_box]
def item(key):return next(o for o in bpy.data.objects if o.get('program_key')==key)
def center(o):return sum(bounds(o),Vector())/8
if office:
 views.append({'name':'library_coffee_cups_close','location':[13.2,6.1,1.25],'target':[14.05,6.05,1.02],'hfov':55})
 plate=center(item('breakout_fruit_plate'));views.append({'name':'library_fruit_plate_close','location':[plate.x-.8,plate.y-.7,plate.z+.75],'target':[plate.x,plate.y,plate.z+.05],'hfov':55})
else:
 plate=center(item('101_fruit_plate'));views.append({'name':'101_dining_library_close','location':[plate.x+.45,plate.y-.75,plate.z+.42],'target':[plate.x,plate.y,plate.z+.05],'hfov':55})
 mapping=json.loads((ref/'room_mapping.json').read_text());camera_constraints=[]
 for unit in (101,102):
  for suffix in ('ensuite','bathroom1','laundry_wc'):
   key=f'{unit}_{suffix}';floor=bpy.data.objects[mapping[key]['room_id']+'.floor'];domain=projected_floor(floor);fz=max(p.z for p in bounds(floor));blockers=[]
   for o in bpy.data.objects:
    if o.type!='MESH' or o.get('reference_scene_owner')!=scene:continue
    kind=o.get('audit_kind','furniture');pts=bounds(o);low=min(v.z for v in pts);high=max(v.z for v in pts)
    if kind in ('furniture','ground_container') or (kind=='fixture' and low<fz+1.2 and high>fz+.35):
     hull=MultiPoint([(v.x,v.y) for v in pts]).convex_hull
     if hull.intersects(domain):blockers.append(hull)
   free=domain.buffer(-.25)
   if blockers:free=free.difference(unary_union(blockers).buffer(.25))
   targets=[center(item(key+'_vanity')),center(item(key+'_wc')),center(item(key+'_shower'))];target=sum(targets,Vector())/3
   x0,y0,x1,y1=domain.bounds;points=[Point(float(x),float(y)) for x in np.arange(x0+.05,x1,.1) for y in np.arange(y0+.05,y1,.1) if free.covers(Point(float(x),float(y)))]
   assert points,'No physically standable review camera for '+key
   eye=max(points,key=lambda p:(p.x-target.x)**2+(p.y-target.y)**2)
   views.append({'name':key+'_wetroom_review','location':[eye.x,eye.y,fz+1.55],'target':[target.x,target.y,fz+1.0],'hfov':95})
   camera_constraints.append({'view':key+'_wetroom_review','standing_clearance_radius_m':.25,'chosen_free_area_m2':free.area,'method':'Actual floor minus padded furnishing bounds; doors assumed operable/open'})
priority=(['breakout_kitchen','library_coffee_cups_close','open_workplace_reference_wide','overview'] if office else ['101_bathroom_wc_reverse','101_kitchen_dining','101_dining_library_close','101_living','102_bathroom_wc_reverse','101_master','overview'])
order={name:i for i,name in enumerate(priority)};views=sorted(views,key=lambda v:order.get(v['name'],len(priority)));assert len({v['name'] for v in views})==len(views)
view_path=base/f'review_views_delivery_r{revision}.json';view_path.write_text(json.dumps(views,indent=2));bpy.ops.file.pack_all();missing=[im.name for im in bpy.data.images if im.users and im.source in ('FILE','TILED') and not(im.packed_file or len(im.packed_files))];assert not missing,missing
unsafe=[o.name for o in bpy.data.objects if o.type=='MESH' and (len(o.data.polygons)>20000 or 'shower' in o.get('program_key','')) and any(m.name in ('realistic_manufactured_edge','surface_weighted_normals') for m in o.modifiers)];assert not unsafe,unsafe
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert digest(source)==before
record={'source':str(source),'source_sha256':before,'packed':str(out),'packed_sha256':digest(out),'source_unchanged':True,'missing_used_images':missing,'unsafe_generic_modifiers':unsafe,'views':str(view_path),'view_count':len(views),'excluded_original_cameras':excluded,'original_cameras_preserved_in':str(base/('review_views_r5.json' if office else 'review_views_r16.json')),'extra_wetroom_camera_constraints':camera_constraints if not office else [],'reopen_render_pending':True,'visual_acceptance':False};(ref/f'packaging_r{revision}.json').write_text(json.dumps(record,indent=2));print(json.dumps({k:v for k,v in record.items() if k not in ('extra_wetroom_camera_constraints','excluded_original_cameras')}),flush=True)
