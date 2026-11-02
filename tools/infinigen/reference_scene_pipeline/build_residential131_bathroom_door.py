"""Install native single-leaf frame and lever in measured bathroom101 opening; preserve all other geometry."""
import bpy,json,sys,math,hashlib
from pathlib import Path
from mathutils import Vector,Matrix
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from compact_wc_contract import mesh_geometry_hash
D=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';base=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';src=base/'scene_candidate_r130_draft.blend';dst=base/'scene_candidate_r131_draft.blend';assert not dst.exists();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();before=sha(src);asset=D/'native_bedroom2_door130/native_asset.blend';contract=json.loads((asset.parent/'native_contract.json').read_text());measurement=json.loads((D/'bathroom130_native_door_measurement.json').read_text());assert measurement['source_sha256']==before;apertures={'rows':[{'unit':101,'aperture_yz_bounds_m':measurement['actual_apertures'][0]['yz_bbox_m']}]};bpy.ops.wm.open_mainfile(filepath=str(src));bpy.context.view_layer.update();old={o.name:([list(v) for v in o.matrix_world],mesh_geometry_hash(o.data) if o.type=='MESH' else None) for o in bpy.context.scene.objects};removed=[];rows=[];fz=.1145347
for ap in apertures['rows']:
 unit=ap['unit'];name='LiteDoorFactory(800570).spawn_asset(6)';bpy.data.objects.remove(bpy.data.objects[name],do_unlink=True);removed.append(name)
 with bpy.data.libraries.load(str(asset),link=False) as (available,loaded):loaded.objects=[contract['object']]
 o=loaded.objects[0];bpy.context.scene.collection.objects.link(o);bpy.context.view_layer.update();M=o.matrix_world.copy();o.parent=None;o.matrix_world=M;o.name='Residential131_101_bathroom2_native_single_door';o['program_key']='101_bathroom2_door';o['audit_kind']='architecture';used={i for f in o.data.polygons for i in f.vertices};frame=[i for i in used if o.data.attributes['door_frame'].data[i].value];moving=[i for i in used if o.data.attributes['door_left'].data[i].value];leaf=[i for i in used if o.data.attributes['door'].data[i].value];assert frame and moving and leaf and not set(frame)&set(moving)
 def pts(ids):return [o.matrix_world@o.data.vertices[i].co for i in ids]
 def bounds(ids):
  p=pts(ids);return Vector([min(v[k] for v in p) for k in range(3)]),Vector([max(v[k] for v in p) for k in range(3)])
 lo,hi=bounds(frame);y0,z0,y1,z1=ap['aperture_yz_bounds_m'];assert abs((y1-y0)-.91158676)<1e-5;boundary=3.;delta=Vector((boundary-(lo.x+hi.x)/2,(y0+y1)/2-(lo.y+hi.y)/2,z1-.003-hi.z));o.matrix_world=Matrix.Translation(delta)@o.matrix_world;bpy.context.view_layer.update();inverse=o.matrix_world.inverted();before_moving=pts(moving);loleaf,hileaf=bounds(leaf);shift=fz+.008-loleaf.z;hinge=Vector((boundary,loleaf.y,0));rotation=Matrix.Rotation((1 if unit==101 else -1)*math.pi/2,4,'Z');expected=[]
 for i,p in zip(moving,before_moving):
  posed=hinge+rotation@(p+Vector((0,0,shift))-hinge);o.data.vertices[i].co=inverse@posed;expected.append(posed)
 embedded=[]
 for i in frame:
  p=o.matrix_world@o.data.vertices[i].co
  if p.z<fz+.03:o.data.vertices[i].co=inverse@(p-Vector((0,0,.04)));embedded.append(i)
 o.data.update();bpy.context.view_layer.update();afterpts=pts(moving);error=max((p-q).length for p,q in zip(afterpts,expected));assert error<1e-5;newlo,newhi=bounds(leaf);assert abs(newlo.z-(fz+.008))<1e-5;loframe,hiframe=bounds(frame);assert abs(hiframe.z-(z1-.003))<1e-5
 rows.append({'unit':unit,'new_object':o.name,'removed_wrong_double_assembly':name,'kept_native_casing':'DoorCasingFactory(800570).spawn_asset(6)','source_aperture_yz_m':[y0,z0,y1,z1],'requested_native_leaf_width_height_depth_m':contract['requested_leaf_width_height_depth_m'],'frame_bbox_m':[list(loframe),list(hiframe)],'open_leaf_bbox_m':[list(newlo),list(newhi)],'floor_leaf_gap_m':newlo.z-fz,'header_rough_gap_m':z1-hiframe.z,'side_rough_gap_m':((y1-y0)-(hiframe.y-loframe.y))/2,'open_deg':90 if unit==101 else -90,'hinge_world_m':list(hinge),'native_moving_vertices':len(moving),'max_world_rigid_pose_error_m':error,'embedded_fixed_lower_frame_points':len(embedded),'native_polygon_count':len(o.data.polygons),'post_generation_rescaling':False})
for o in bpy.context.scene.objects:
 if o.name not in old:continue
 M,h=old[o.name];assert M==[list(v) for v in o.matrix_world],o.name
 if o.type=='MESH':assert h==mesh_geometry_hash(o.data),o.name
bpy.ops.wm.save_as_mainfile(filepath=str(dst));assert sha(src)==before;(D/'bathroom_door131_build.json').write_text(json.dumps({'source':str(src),'source_sha256':before,'candidate':str(dst),'candidate_sha256':sha(dst),'native_asset':str(asset),'native_asset_sha256':sha(asset),'rows':rows,'unrelated_raw_geometry_and_matrices_unchanged':True,'accepted':False,'scope':'Native original820x2300x45mm single door and lever replace bathroom101 inappropriate double leaves and push bars. Actual evaluated wall aperture911.6mm; retained native casing. Rigid movable leaf/lever rotation only; fixed lower frame embedded40mm. No furniture/fixture resizing. Body clearance, dynamic sweep and matched RGB remain required; source130 full review running.'},indent=2));print('BATHROOM131_NATIVE_SINGLE_DOOR_SAVED',rows,flush=True)
