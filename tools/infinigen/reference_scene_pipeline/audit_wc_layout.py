"""Eight measured seat heights; two mirrored bathroom2 entry/front-clearance checks."""
import argparse,json,hashlib
from pathlib import Path
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from wc_layout_checks import bounds,seat_measurement,bathroom2_entry_check,evaluated_geometry
from compact_wc_contract import verify_compact_body,verify_compact_flush

def main():
 p=argparse.ArgumentParser();p.add_argument('--blend',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();src=a.blend.resolve();bpy.ops.wm.open_mainfile(filepath=str(src));ref=Path(__file__).resolve().parents[3]/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';mapping=json.loads((ref/'room_mapping.json').read_text());wcs=[o for o in bpy.data.objects if o.type=='MESH' and str(o.get('program_key','')).endswith('_wc')];doors=[o for o in bpy.data.objects if o.type=='MESH' and 'DoorFactory' in o.name];rows=[];errors=[]
 if len(wcs)!=8:errors.append({'reason':'expected8 toilets','actual':len(wcs)})
 for o in wcs:
  measurement=seat_measurement(o);lo,hi=bounds(o);dims=sorted([hi.x-lo.x,hi.y-lo.y]);row={'object':o.name,'key':o['program_key'],'seat':measurement,'horizontal_dimensions_sorted_m':dims,'pass':.40<=measurement['seat_height_m']<=.44 and .34<=dims[0]<=.46 and .62<=dims[1]<=.76}
  floor=bpy.data.objects.get(mapping[o['program_key'][:-3]]['room_id']+'.floor');assert floor is not None
  ev,fmesh,points=evaluated_geometry(floor);ftree=BVHTree.FromPolygons(points,[tuple(f.vertices) for f in fmesh.polygons]);ev.to_mesh_clear();hit,n,i,distance=ftree.ray_cast(Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z+.02)),Vector((0,0,-1)),1);row['actual_floor_support_gap_m']=lo.z-hit.z if hit is not None else None
  if o.get('wc_variant')=='native_concealed_cistern':
   body=verify_compact_body(o,ref);flush=verify_compact_flush(o,ref);row['compact_contract']={'body':body,'flush':flush};row['pass']=(.40<=measurement['seat_height_m']<=.44 and .34<=dims[0]<=.46 and abs(dims[1]-body.get('expected_depth_m',-1))<.003 and body['pass'] and flush['pass'])
  elif o.get('wc_variant') not in [None,'standard']:row['pass']=False;row['unknown_variant']=o.get('wc_variant')
  row['pass']=row['pass'] and row['actual_floor_support_gap_m'] is not None and abs(row['actual_floor_support_gap_m'])<.003
  if not row['pass']:errors.append({'reason':'seat_height_or_horizontal_dimensions_or_variant_contract','record':row})
  if o['program_key'] in ['101_bathroom2_wc','102_bathroom2_wc']:
   unit=int(o['program_key'][:3]);room=mapping[f'{unit}_bathroom2']['polygon_m'];fixtures=[q for q in bpy.data.objects if q.type=='MESH' and q.get('program_key') in [f'{unit}_bathroom2_shower',f'{unit}_bathroom2_vanity'] and any(k in q.name for k in ['ShowerEnclosureFactory','HomeVanityFactory'])];assert len(fixtures)==2
   row['entry']=bathroom2_entry_check(o,room,unit,doors,fixtures)
   if not row['entry']['pass']:errors.append({'reason':'bathroom2_entry_or_front_clearance','key':row['key'],'entry':row['entry']})
  rows.append(row)
 d={'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'auditor_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'helper_sha256':hashlib.sha256(Path(__file__).with_name('wc_layout_checks.py').read_bytes()).hexdigest(),'compact_contract_helper_sha256':hashlib.sha256(Path(__file__).with_name('compact_wc_contract.py').read_bytes()).hexdigest(),'records':rows,'errors':errors,'photorealism_accepted':False,'scope':'Measured actual upward seat annuli all8;standard dimensions unchanged,compact variants require exact reviewed prototype body and4 wall-supported flush parts. Conservative projected bounds for two bathroom2 entry/front-clearance regions. Project design thresholds,not legal compliance. Other6 WC entry/door sweeps and full navigation remain unverified.'};a.out.write_text(json.dumps(d,indent=2));print(json.dumps({'wc_count':len(wcs),'errors':len(errors),'out':str(a.out)}),flush=True);return bool(errors)
if __name__=='__main__':raise SystemExit(main())
