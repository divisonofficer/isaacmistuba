"""All ten current-source native WC dimensions, actual seat annuli and floor rays."""
import bpy,json,hashlib,sys
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from wc_layout_checks import evaluated_geometry,bounds,seat_measurement
from compact_wc_contract import mesh_geometry_hash
d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r116_draft.blend';before=hashlib.sha256(src.read_bytes()).hexdigest();contract=json.loads((d/'native_fullsize_wc100/contract.json').read_text());mapping=json.loads((d/'room_mapping.json').read_text());bpy.ops.wm.open_mainfile(filepath=str(src));floors=[]
for o in bpy.context.scene.objects:
 if o.type!='MESH' or not o.name.endswith('.floor'):continue
 lo,hi=bounds(o)
 if hi.z>.5:continue
 ev,me,points=evaluated_geometry(o);t=BVHTree.FromPolygons(points,[tuple(f.vertices) for f in me.polygons]);ev.to_mesh_clear();floors.append((o.name,t))
rows=[]
for o in bpy.context.scene.objects:
 key=str(o.get('program_key',''))
 if o.type!='MESH' or not key.endswith('_wc'):continue
 lo,hi=bounds(o);seat=seat_measurement(o);size=hi-lo;support=[]
 for fx,fy in [(.3,.3),(.5,.3),(.7,.3),(.3,.5),(.5,.5),(.7,.5),(.3,.7),(.5,.7),(.7,.7)]:
  start=Vector((lo.x+size.x*fx,lo.y+size.y*fy,lo.z+.02));hits=[]
  for name,t in floors:
   loc,n,i,dist=t.ray_cast(start,Vector((0,0,-1)),.3)
   if loc is not None:hits.append((dist,name,loc.z))
  if hits:
   _,name,z=min(hits);support.append({'xy':list(start.xy),'floor_object':name,'gap_m':lo.z-z})
  else:support.append({'xy':list(start.xy),'floor_object':None,'gap_m':None})
 dim=sorted([size.x,size.y]);native=mesh_geometry_hash(o.data)==contract['mesh_geometry_sha256'];bounded=native and all(abs(x-1)<1e-6 for x in o.scale) and .40<=seat['seat_height_m']<=.42 and .34<=dim[0]<=.46 and .62<=dim[1]<=.76 and all(x['gap_m'] is not None and abs(x['gap_m'])<.003 for x in support);rows.append({'key':key,'object':o.name,'bbox_m':[list(lo),list(hi)],'dimensions_xyz_m':list(size),'seat_height_m':seat['seat_height_m'],'native_product_geometry_identical':native,'unit_scale':list(o.scale),'floor_support_samples':support,'canonical_room_tag_present':key[:-3] in mapping,'bounded_product_size_and_floor_support_pass':bounded})
assert len(rows)==10;assert hashlib.sha256(src.read_bytes()).hexdigest()==before;out={'source':str(src),'source_sha256':before,'rows':rows,'actual_wc_count':len(rows),'canonical_tagged_wc_rooms':sum(x['canonical_room_tag_present'] for x in rows),'all_bounded_product_size_and_floor_support_pass':all(x['bounded_product_size_and_floor_support_pass'] for x in rows),'scope':'Saved latest combined116: actual evaluated seat annuli and extents, native raw product identity and90 floor rays. Does NOT certify bowl completeness, walls/fixture collision, door sweep, side clearance or600mm paths. Missing two canonical room tags explicitly tracked; no whole navigation acceptance.','accepted':False};(d/'wc116_current_product_support_audit.json').write_text(json.dumps(out,indent=2));print('WC116_CURRENT_AUDIT',len(rows),out['canonical_tagged_wc_rooms'],out['all_bounded_product_size_and_floor_support_pass'])
