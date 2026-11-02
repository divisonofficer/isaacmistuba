"""Actual evaluated side-clearance rays supplement conservative projection checks."""
import bpy,json,hashlib,sys
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from wc_layout_checks import evaluated_geometry
from bathroom_access_contract100 import DOORS
D=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';meta=json.load(open(D/'realism_refinement_r102.json'));audit={'source':meta['candidate'],'source_sha256':meta['candidate_sha256'],'records':meta['wc_access100']['records']};assert hashlib.sha256(Path(audit['source']).read_bytes()).hexdigest()==audit['source_sha256'];mapping=json.load(open(D/'room_mapping.json'));bpy.ops.wm.open_mainfile(filepath=audit['source']);records=[]
for r in audit['records']:
 key=r['key'];doorname=DOORS[key];casename=doorname.replace('LiteDoorFactory','DoorCasingFactory').replace('GlassPanelDoorFactory','DoorCasingFactory');room=mapping[key]['room_id'];wc=bpy.data.objects[r['object']];forward=wc.matrix_world.to_3x3()@Vector((1,0,0));left=Vector((-forward.y,forward.x,0)).normalized();center=Vector(r['bowl_centre_m']);candidates=[]
 for obj in bpy.context.scene.objects:
  if obj.type!='MESH' or obj==wc:continue
  if obj.name in [room+'.wall',room+'.exterior',doorname,casename] or obj.name.startswith('Realism_'+room+'_wall_tile_') or str(obj.get('program_key','')).startswith((key+'_vanity',key+'_shower')):candidates.append(obj)
 hits=[]
 for sign in [1,-1]:
  nearest=None
  for obj in candidates:
   ev,mesh,pts=evaluated_geometry(obj);axis=mesh.attributes.get('axis_group') if obj.name==doorname else None;faces=[tuple(f.vertices) for f in mesh.polygons if axis is None or not any(axis.data[i].value>.5 for i in f.vertices)];tree=BVHTree.FromPolygons(pts,faces);hit=tree.ray_cast(center,left*sign,8);ev.to_mesh_clear()
   if hit[0] is not None and (nearest is None or hit[3]<nearest['distance_m']):nearest={'object':obj.name,'distance_m':hit[3],'point_m':list(hit[0])}
  hits.append(nearest or {'object':None,'distance_m':None,'no_selected_surface_within_8m':True})
 row={'key':key,'left':hits[0],'right':hits[1],'pass':all(x['distance_m'] is None or x['distance_m']>=.4 for x in hits)};records.append(row);print('SIDE_RAYS',row,flush=True)
result={'source':audit['source'],'source_sha256':audit['source_sha256'],'records':records,'pass':all(r['pass'] for r in records),'scope':'Actual evaluated wall,wall tile,tagged shower/vanity,real door body/handle/frame and casing side rays at seat annulus centre; complements conservative full fixture projections. Not a complete ergonomic volume or building-code check.'};(D/'bathroom_access_r102_side_rays.json').write_text(json.dumps(result,indent=2));assert result['pass']
