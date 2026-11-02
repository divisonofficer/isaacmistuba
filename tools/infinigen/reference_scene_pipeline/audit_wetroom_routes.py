"""Casing inner-face ray measurements and bounded planar disc access diagnostics.
Does not model moving door leaves, 3D human articulation or certify whole navigation.
"""
import bpy,json,argparse,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from shapely.geometry import Polygon,Point,box
from shapely.ops import unary_union
from wc_layout_checks import evaluated_geometry,footprint

def main():
 p=argparse.ArgumentParser();p.add_argument('--blend',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();src=a.blend.resolve();bpy.ops.wm.open_mainfile(filepath=str(src));ref=Path(__file__).resolve().parents[3]/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';mapping=json.loads((ref/'room_mapping.json').read_text());openings=[]
 for o in bpy.data.objects:
  if o.type!='MESH' or 'DoorCasingFactory' not in o.name:continue
  ev,me,pts=evaluated_geometry(o);lo=[min(v[k] for v in pts) for k in range(3)];hi=[max(v[k] for v in pts) for k in range(3)]
  if hi[1]-lo[1]>.5 and hi[0]-lo[0]<.5:
   tree=BVHTree.FromPolygons(pts,[tuple(f.vertices) for f in me.polygons]);center=Vector(((lo[0]+hi[0])/2,(lo[1]+hi[1])/2,lo[2]+1.0));left=tree.ray_cast(center,Vector((0,-1,0)),2)[0];right=tree.ray_cast(center,Vector((0,1,0)),2)[0]
   if left is not None and right is not None:openings.append({'casing':o.name,'wall_x':center.x,'inner_y':[left.y,right.y],'width_m':right.y-left.y,'ray_z_m':center.z})
  ev.to_mesh_clear()
 rows=[]
 for wc in bpy.data.objects:
  key=str(wc.get('program_key',''))
  if wc.type!='MESH' or not key.endswith('_wc'):continue
  room_key=key[:-3];room=Polygon(mapping[room_key]['polygon_m']);x0,y0,x1,y1=room.bounds;unit=int(key[:3]);wall=x1 if unit==101 else x0;matches=[v for v in openings if abs(v['wall_x']-wall)<.15 and y0<sum(v['inner_y'])/2<y1];row={'room':room_key,'opening_candidates':matches,'routes':[]}
  fixtures=[o for o in bpy.data.objects if o.type=='MESH' and o.get('program_key') in [room_key+'_vanity',room_key+'_shower'] and any(n in o.name for n in ['HomeVanityFactory','ShowerEnclosureFactory'])];assert len(fixtures)==2
  body=footprint(wc);obstacles=[body]+[footprint(o) for o in fixtures];fw=wc.matrix_world.to_3x3()@Vector((1,0,0));fw.z=0;fw.normalize();side=Vector((-fw.y,fw.x,0));corners=[Vector((x,y,0)) for x,y in list(body.exterior.coords)[:-1]];tip=max(v.dot(fw) for v in corners);lat=(min(v.dot(side) for v in corners)+max(v.dot(side) for v in corners))/2
  if len(matches)==1:
   opening=matches[0];low,high=opening['inner_y']
   for radius in [.2,.25,.3]:
    margin=.025;clear=radius+margin;interior=room.buffer(-(.1+radius));free=interior.difference(unary_union([o.buffer(clear,resolution=16) for o in obstacles]));q=fw*(tip+radius+.05)+side*lat;target=Point(q.x,q.y);parts=list(free.geoms) if free.geom_type=='MultiPolygon' else [free];component=next((g for g in parts if g.buffer(1e-7).covers(target)),None);start=None;start_x=wall-(.1+radius) if unit==101 else wall+(.1+radius)
    if component is not None and high-low>2*clear:
     count=max(1,int((high-low-2*clear)/.01))
     for i in range(count+1):
      y=low+clear+(high-low-2*clear)*i/count
      if component.buffer(1e-7).covers(Point(start_x,y)):start=[start_x,y];break
    row['routes'].append({'disc_diameter_m':radius*2,'obstacle_margin_m':margin,'room_wall_inset_m':.1,'wc_front_target_xy':[target.x,target.y],'entry_center_xy':start,'same_free_component':start is not None,'method':'Actual casing inner-face rays;connected component of room inset minus evaluated fixture footprint buffers. No moving-door envelope.'})
  row['entry_resolution']='measured_casing_inner_faces' if len(matches)==1 else 'unresolved';rows.append(row)
 assert len(rows)==8;d={'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'auditor_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'openings':openings,'records':rows,'photorealism_accepted':False,'scope':'Planar disc reachability from measured casing opening to WC-front target for0.4/0.5/0.6m diameters. Independent complement to conservative rectangular entry/front checks,not a replacement pass. Current/moving door leaves, actual 3D fixture voids, human articulation andwhole-scene nav remain unverified.'};a.out.write_text(json.dumps(d,indent=2));print(json.dumps({'rooms':len(rows),'resolved_entries':sum(r['entry_resolution']=='measured_casing_inner_faces' for r in rows),'routes_0_6m':sum(any(q['disc_diameter_m']==.6 and q['same_free_component'] for q in r['routes']) for r in rows)}),flush=True)
if __name__=='__main__':main()
