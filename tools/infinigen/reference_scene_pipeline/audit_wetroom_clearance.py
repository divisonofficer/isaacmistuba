"""Independent bounded diagnosis of all8 WC entry/front regions; doesnot alter source."""
import argparse,json,hashlib
from pathlib import Path
import bpy
from mathutils import Vector
from shapely.geometry import Polygon,MultiPoint,box
from wc_layout_checks import bounds,evaluated_geometry,footprint

def main():
 p=argparse.ArgumentParser();p.add_argument('--blend',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();src=a.blend.resolve();bpy.ops.wm.open_mainfile(filepath=str(src));ref=Path(__file__).resolve().parents[3]/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';mapping=json.loads((ref/'room_mapping.json').read_text());frames=[]
 for o in bpy.data.objects:
  if o.type!='MESH' or 'DoorFactory' not in o.name:continue
  ev,me,pts=evaluated_geometry(o);attr=me.attributes.get('door_frame')
  if attr and attr.domain=='POINT':
   xy=[(v.x,v.y) for v,t in zip(pts,attr.data) if t.value>.5]
   if len(xy)>=3:
    hull=MultiPoint(xy).convex_hull
    if hull.geom_type=='Polygon':
     x0,y0,x1,y1=hull.bounds
     if y1-y0>.5 and x1-x0<.15:frames.append({'object':o.name,'bounds':[x0,y0,x1,y1]})
  ev.to_mesh_clear()
 rows=[];errors=[]
 for o in bpy.data.objects:
  key=str(o.get('program_key',''))
  if o.type!='MESH' or not key.endswith('_wc'):continue
  room_key=key[:-3];room=Polygon(mapping[room_key]['polygon_m']);x0,y0,x1,y1=room.bounds;unit=int(key[:3]);wall=x1 if unit==101 else x0
  candidates=[f for f in frames if abs((f['bounds'][0]+f['bounds'][2])/2-wall)<.12 and min(f['bounds'][3],y1)-max(f['bounds'][1],y0)>.5]
  body=footprint(o);fw=o.matrix_world.to_3x3()@Vector((1,0,0));fw.z=0;fw.normalize();side=Vector((-fw.y,fw.x,0));corners=[Vector((x,y,0)) for x,y in list(body.exterior.coords)[:-1]];tip=max(v.dot(fw) for v in corners);lat=(min(v.dot(side) for v in corners)+max(v.dot(side) for v in corners))/2;front=Polygon([(fw*t+side*s).xy[:] for t,s in [(tip,lat-.38),(tip+.65,lat-.38),(tip+.65,lat+.38),(tip,lat+.38)]])
  fixtures=[q for q in bpy.data.objects if q.type=='MESH' and q.get('program_key') in [room_key+'_shower',room_key+'_vanity'] and any(n in q.name for n in ['ShowerEnclosureFactory','HomeVanityFactory'])];assert len(fixtures)==2
  overlaps=[{'object':q.name,'program_key':q['program_key'],'area_m2':front.intersection(footprint(q)).area} for q in fixtures];row={'wc':o.name,'room':room_key,'room_polygon_xy':list(room.exterior.coords),'wc_footprint_xy':list(body.exterior.coords),'front_region_xy':list(front.exterior.coords),'front_inside_room':room.buffer(1e-6).covers(front),'front_fixture_overlaps':overlaps,'doorway_candidates':candidates,'entry_status':'unresolved_ambiguous_or_missing_full_frame','entry_approach_overlap_m2':None}
  if len(candidates)==1:
   f=candidates[0];lo,hi=f['bounds'][1],f['bounds'][3];approach=box(wall-.8,lo-.3,wall+.02,hi+.3) if unit==101 else box(wall-.02,lo-.3,wall+.8,hi+.3);row.update(entry_status='measured',entry_approach_xy=list(approach.exterior.coords),entry_approach_overlap_m2=body.intersection(approach).area)
  row['pass']=row['entry_status']=='measured' and row['entry_approach_overlap_m2']<1e-7 and row['front_inside_room'] and all(x['area_m2']<1e-7 for x in overlaps)
  if not row['pass']:errors.append({'room':room_key,'entry_status':row['entry_status'],'entry_approach_overlap_m2':row['entry_approach_overlap_m2'],'front_inside_room':row['front_inside_room'],'front_fixture_overlaps':overlaps})
  rows.append(row)
 assert len(rows)==8
 d={'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'auditor_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'helper_sha256':hashlib.sha256(Path(__file__).with_name('wc_layout_checks.py').read_bytes()).hexdigest(),'records':rows,'errors':errors,'scope':'All8 room diagnostics using actual evaluated fixtures and tagged full doorway frames. Bounds are conservative; frame ambiguity remains unresolved, not a pass. Project regions:0.8m inward/0.3m jamb sides and0.65x0.76m front. No complete door-angle sweep ortriangle collision/nav certification.','photorealism_accepted':False};a.out.write_text(json.dumps(d,indent=2));print(json.dumps({'rooms':len(rows),'failed_or_unresolved':len(errors),'out':str(a.out)}),flush=True);return bool(errors)
if __name__=='__main__':raise SystemExit(main())
