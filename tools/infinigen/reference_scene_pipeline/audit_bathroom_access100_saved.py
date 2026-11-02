"""Independent saved100 geometry,foot support,all8door/route/side checks and real aperture rays."""
import bpy,json,hashlib,sys
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from bathroom_access_contract100 import assess_wc,DOORS
from wc_layout_checks import bounds,evaluated_geometry
from compact_wc_contract import mesh_geometry_hash
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';m=json.loads((D/'realism_refinement_r100.json').read_text());C=Path(m['candidate']);out=D/'bathroom_access_r100_saved_audit.json';assert not out.exists();sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();assert sha(C)==m['candidate_sha256'];contract=json.loads(Path(m['wc_access100']['prototype_contract']).read_text());assert sha(contract['prototype_source'])==contract['prototype_source_sha256'];bpy.ops.wm.open_mainfile(filepath=str(C));mapping=json.loads((D/'room_mapping.json').read_text());errors=[];records=[]
def tree(objects):
 points=[];faces=[]
 for obj in objects:
  ev,mesh,pts=evaluated_geometry(obj);offset=len(points);points.extend(pts);faces.extend(tuple(i+offset for i in f.vertices) for f in mesh.polygons);ev.to_mesh_clear()
 return BVHTree.FromPolygons(points,faces)
for wc in [o for o in bpy.context.scene.objects if o.type=='MESH' and str(o.get('program_key','')).endswith('_wc')]:
 key=wc['program_key'][:-3];program=mapping[key];record=assess_wc(wc,key,program);record['native_geometry_identity']=mesh_geometry_hash(wc.data)==contract['mesh_geometry_sha256'];record['tank_included']=True
 if not record['native_geometry_identity'] or max(abs(v-1) for v in wc.scale)>1e-6:errors.append(key+':native_mesh_or_scale')
 if not(.37<record['width_m']<.39 and .65<record['depth_m']<.70 and .400<=record['seat_height_m']<=.420):errors.append(key+':dimensions')
 floor=[bpy.data.objects[program['room_id']+'.floor']]+[o for o in bpy.context.scene.objects if o.name.startswith('Realism_'+program['room_id']+'_floor_tile_')];floor_tree=tree(floor);wp=[wc.matrix_world@v.co for v in wc.data.vertices];low=min(p.z for p in wp);foot=[p for p in wp if p.z<low+1e-5];gaps=[]
 for point in foot:
  hit=floor_tree.ray_cast(point+Vector((0,0,.003)),Vector((0,0,-1)),.02)[0];gaps.append(None if hit is None else point.z-hit.z)
 record['actual_floor_support_gap_range_m']=[min(g for g in gaps if g is not None),max(g for g in gaps if g is not None)] if any(g is not None for g in gaps) else None
 if any(g is None or g<-.0001 or g>.002 for g in gaps):errors.append(key+':floor_support')
 room_objects=[o for o in bpy.context.scene.objects if o.name in [program['room_id']+'.wall',program['room_id']+'.exterior'] or o.name.startswith('Realism_'+program['room_id']+'_wall_tile_')];case=bpy.data.objects[DOORS[key].replace('LiteDoorFactory','DoorCasingFactory').replace('GlassPanelDoorFactory','DoorCasingFactory')];walltree=tree(room_objects+[case]);ray_rows=[]
 if record['path_polyline_xy_m']:
  from shapely.geometry import LineString
  wallx=max(p[0] for p in program['polygon_m']) if key.startswith('101') else min(p[0] for p in program['polygon_m']);cross=LineString(record['path_polyline_xy_m']).intersection(LineString([(wallx,-100),(wallx,100)]));crosspoints=list(cross.geoms) if hasattr(cross,'geoms') else [cross]
  center=next((g for g in crosspoints if g.geom_type=='Point'),None)
  if center is None:errors.append(key+':no_wall_crossing')
  else:
   for dy in [-.3,-.2,-.1,0,.1,.2,.3]:
    for dz in [.12,.7,1.3,1.9]:
     p=Vector((wallx-.30,center.y+dy,low+dz));hit=walltree.ray_cast(p,Vector((1,0,0)),.60)[0];ray_rows.append({'dy':dy,'height':dz,'blocked':hit is not None})
   if any(r['blocked'] for r in ray_rows):errors.append(key+':actual_aperture_ray_block')
 record['actual_aperture_ray_tests']=ray_rows
 if not record['pass']:errors.append(key+':clearance_or_path')
 records.append(record);print('SAVED_WC100',key,record['pass'],record['path_min_clear_width_m'],'apertureblocked',sum(x['blocked'] for x in ray_rows),flush=True)
assert len(records)==8;out.write_text(json.dumps({'source':str(C),'source_sha256':sha(C),'helper_sha256':sha(Path(__file__).with_name('bathroom_access_contract100.py')),'auditor_sha256':sha(Path(__file__)),'prototype_contract':contract,'records':records,'errors':errors,'pass':not errors,'photorealism_accepted':False,'scope':'Native mesh identity/scale,measuredseat/all8widths,actual floor rays,real fixed casing/jamb projection,continuous conservative door sweep and explicit600mm pedestrian disk routes,28wall/casing aperture rays perroom. Not building-code/plumbing/manufacturer hinge/load certification.'},indent=2));assert not errors,errors
